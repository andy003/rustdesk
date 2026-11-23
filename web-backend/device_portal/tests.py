import sqlite3
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.utils import timezone
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from .admin_site import PortalAdminAuthenticationForm
from .device_binding import DOMAIN
from .models import Device, WechatLoginAttempt


class ClientAccountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        accounts = get_user_model().objects
        cls.password = "rustdesk-test-account-69"
        cls.owner = accounts.create_user("owner", password=cls.password)
        cls.other = accounts.create_user("other", password=cls.password)
        cls.first = Device.objects.create(
            name="Office PC", rustdesk_id="123456789", owner=cls.owner
        )
        cls.second = Device.objects.create(
            name="Workshop PC", rustdesk_id="office-2", owner=cls.owner
        )
        cls.unrelated = Device.objects.create(
            name="Other PC", rustdesk_id="987654321", owner=cls.other
        )

    def login(self, username, password):
        return self.client.post(
            "/api/login",
            {"type": "account", "username": username, "password": password},
            content_type="application/json",
        )

    def auth_header(self, username):
        response = self.login(username, self.password)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["type"], "access_token")
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    def test_client_account_lists_only_owned_devices(self):
        headers = self.auth_header(self.owner.username)
        current = self.client.post("/api/currentUser", "{}", "application/json", headers=headers)
        self.assertEqual(current.json()["name"], self.owner.username)
        self.assertIs(current.json()["require_device_password"], True)

        page = self.client.get("/api/peers?pageSize=1", headers=headers).json()
        self.assertEqual(page["total"], 2)
        self.assertEqual(page["data"], [{
            "id": self.first.rustdesk_id,
            "info": {"device_name": self.first.name, "os": ""},
            "status": 1,
            "user_name": self.owner.username,
        }])
        page = self.client.get("/api/peers?pageSize=1&current=2", headers=headers).json()
        self.assertEqual([device["id"] for device in page["data"]], [self.second.rustdesk_id])

        headers = self.auth_header(self.other.username)
        page = self.client.get("/api/peers", headers=headers).json()
        self.assertEqual([device["id"] for device in page["data"]], [self.unrelated.rustdesk_id])

    def test_native_api_requires_credentials_even_with_a_browser_session(self):
        self.assertEqual(self.login("owner", "incorrect password").status_code, 401)

        admin = get_user_model().objects.create_superuser("admin", password=self.password)
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(admin)
        self.assertEqual(browser.get("/admin/").status_code, 200)
        self.assertEqual(browser.get("/api/peers").status_code, 401)
        self.assertEqual(self.login("admin", self.password).status_code, 401)

    def test_managed_network_requires_client_authentication(self):
        network = {
            "id_server": "rustdesk.example:21116",
            "relay_server": "rustdesk.example:21117",
            "public_key": "TCJN2BBOhAzds7e/ltHTb4C3PhRyKOdhyPfOIsMimDQ=",
        }
        with self.settings(MANAGED_NETWORK=network):
            self.assertNotIn("managed_network", self.login("owner", "wrong").json())
            login = self.login("owner", self.password).json()
            self.assertEqual(login["managed_network"], network)
            current = self.client.post(
                "/api/currentUser", headers={"Authorization": f"Bearer {login['access_token']}"}
            )
            self.assertEqual(current.json()["managed_network"], network)

    def test_admin_requires_totp_without_redisplaying_the_password(self):
        admin = get_user_model().objects.create_superuser("admin", password=self.password)
        device = TOTPDevice.objects.create(user=admin, name="Authenticator")
        credentials = {"username": admin.username, "password": self.password}

        missing = PortalAdminAuthenticationForm(data=credentials)
        self.assertFalse(missing.is_valid())
        self.assertNotIn(self.password, str(missing["password"]))

        verified = PortalAdminAuthenticationForm(
            data={**credentials, "otp_token": f"{totp(device.bin_key):06d}"}
        )
        self.assertTrue(verified.is_valid(), verified.errors)

    def test_logout_and_password_change_revoke_native_sessions(self):
        headers = self.auth_header(self.owner.username)
        self.assertEqual(self.client.post("/api/logout", headers=headers).status_code, 200)
        self.assertEqual(self.client.get("/api/peers", headers=headers).status_code, 401)

        other_session = self.auth_header(self.owner.username)
        self.owner.set_password("another-rustdesk-account-password")
        self.owner.save(update_fields=["password"])
        self.assertEqual(self.client.get("/api/peers", headers=other_session).status_code, 401)

    def test_bind_requires_registered_device_key_and_preserves_owner(self):
        with TemporaryDirectory() as tmp:
            database = str(Path(tmp) / "rendezvous.sqlite3")
            device_id = "654321987"
            key = Ed25519PrivateKey.generate()
            with sqlite3.connect(database) as db:
                db.execute("CREATE TABLE peer (id TEXT PRIMARY KEY, pk BLOB, status INTEGER)")
                db.execute("INSERT INTO peer VALUES (?, ?, NULL)",
                           (device_id, key.public_key().public_bytes_raw()))
            with self.settings(RENDEZVOUS_DATABASE=database):
                owner = self.auth_header(self.owner.username)
                other = self.auth_header(self.other.username)

                def challenge(headers):
                    response = self.client.post("/api/device-binding/challenge", {"id": device_id},
                                                "application/json", headers=headers)
                    return response.json()["challenge"]

                def bind(headers, nonce, private_key):
                    signature = private_key.sign(DOMAIN + nonce.encode("ascii")).hex()
                    return self.client.post("/api/device-binding", {
                        "id": device_id, "challenge": nonce, "signature": signature,
                        "name": "Managed desktop", "os": "linux",
                    }, "application/json", headers=headers)

                nonce = challenge(owner)
                self.assertEqual(bind(other, nonce, key).status_code, 403)
                self.assertEqual(bind(owner, nonce, Ed25519PrivateKey.generate()).status_code, 403)
                self.assertEqual(bind(owner, nonce, key).status_code, 200)
                self.assertEqual(bind(other, challenge(other), key).status_code, 409)

                response = self.client.get("/api/peers", headers=owner)
                self.assertIn(device_id, [peer["id"] for peer in response.json()["data"]])
                response = self.client.get("/api/peers", headers=other)
                self.assertNotIn(device_id, [peer["id"] for peer in response.json()["data"]])


@override_settings(
    WECHAT_ENABLED=True,
    WECHAT_APP_ID="wx_test_application",
    WECHAT_CALLBACK_URL="https://rustdesk.example/api/wechat/callback",
)
class WechatLoginTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.password = "rustdesk-test-password"
        cls.owner = get_user_model().objects.create_user("owner", password=cls.password)
        cls.device = Device.objects.create(
            owner=cls.owner, name="Office desktop", rustdesk_id="123456789"
        )

    def bearer(self, token):
        return {"Authorization": f"Bearer {token}"}

    def post_wechat(self, action, token="", body=None):
        return self.client.post(
            f"/api/wechat/{action}", body if body is not None else {},
            content_type="application/json", headers=self.bearer(token),
        )

    def approve(self, start):
        url = urlsplit(start["url"])
        self.assertEqual((url.scheme, url.netloc, url.path), (
            "https", "open.weixin.qq.com", "/connect/qrconnect",
        ))
        params = parse_qs(url.query)
        self.assertEqual(params["scope"], ["snsapi_login"])
        state = params["state"][0]
        self.assertNotEqual(state, start["verifier"])
        query = {"state": state, "code": "test-provider-code"}
        with patch("device_portal.wechat.exchange_code", return_value="wechat-identity") as exchange:
            self.assertEqual(self.client.get("/api/wechat/callback", query).status_code, 200)
            self.assertEqual(self.client.get("/api/wechat/callback", query).status_code, 400)
            exchange.assert_called_once_with(query["code"])

    def test_link_and_sign_in_use_existing_client_account(self):
        auth = self.client.post("/api/login", {
            "type": "account", "username": self.owner.username, "password": self.password,
        }, content_type="application/json").json()
        self.assertEqual(self.post_wechat("link", auth["access_token"]).status_code, 401)
        link = self.post_wechat("link", auth["access_token"], {"password": self.password}).json()
        self.assertEqual(self.post_wechat("poll", link["verifier"]).json(), {"status": "pending"})
        self.approve(link)
        self.assertEqual(self.post_wechat("poll", link["verifier"]).json(), {"status": "linked"})

        start = self.post_wechat("start").json()
        self.approve(start)
        success = self.post_wechat("poll", start["verifier"]).json()
        self.assertEqual(success["user"]["name"], self.owner.username)
        self.assertIs(success["user"]["require_device_password"], True)
        peers = self.client.get("/api/peers", headers=self.bearer(success["access_token"])).json()
        self.assertEqual([device["id"] for device in peers["data"]], [self.device.rustdesk_id])
        self.assertEqual(self.post_wechat("poll", start["verifier"]).status_code, 410)

    def test_unknown_wechat_and_expired_attempt_do_not_issue_sessions(self):
        start = self.post_wechat("start").json()
        self.assertEqual(self.post_wechat("link", body={"password": self.password}).status_code, 401)
        self.assertEqual(self.client.get("/api/wechat/callback", {"state": "x" * 43}).status_code, 400)
        self.approve(start)
        unknown = self.post_wechat("poll", start["verifier"])
        self.assertEqual(unknown.status_code, 403)
        self.assertNotIn("access_token", unknown.json())

        expired = self.post_wechat("start").json()
        WechatLoginAttempt.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.post_wechat("poll", expired["verifier"]).status_code, 410)
