import json
import logging
import re
import secrets
import sqlite3
from contextlib import closing
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from django.conf import settings
from django.core import signing
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .client_api import client_session_required
from .models import Device


LOGGER = logging.getLogger(__name__)
DOMAIN = b"rustdesk-account-device-binding-v1\0"
SALT = "rustdesk.device-binding.v1"
ID_FORMAT = re.compile(r"(?:[0-9]{1,16}|[a-zA-Z][a-zA-Z0-9_-]{5,15})")


def binding_request(request):
    try:
        if len(request.body) > 4096:
            return None
        body = json.loads(request.body)
    except (ValueError, RecursionError):
        return None
    if not isinstance(body, dict):
        return None
    device_id = body.get("id")
    if not isinstance(device_id, str) or not ID_FORMAT.fullmatch(device_id):
        return None
    return body


def registered_key(device_id):
    uri = Path(settings.RENDEZVOUS_DATABASE).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=2)) as database:
        row = database.execute(
            "SELECT pk FROM peer WHERE id = ? AND (status IS NULL OR status = 1)",
            (device_id,),
        ).fetchone()
    return row[0] if row and isinstance(row[0], bytes) and len(row[0]) == 32 else None


@csrf_exempt
@require_POST
@client_session_required
def challenge(request, session):
    if not settings.RENDEZVOUS_DATABASE:
        return JsonResponse({"error": "Device binding is unavailable"}, status=404)
    body = binding_request(request)
    if body is None:
        return JsonResponse({"error": "Invalid device registration"}, status=400)
    challenge_token = signing.dumps(
        {"session": session.pk, "id": body["id"], "nonce": secrets.token_hex(16)},
        salt=SALT,
    )
    return JsonResponse({"challenge": challenge_token})


@csrf_exempt
@require_POST
@client_session_required
def bind_device(request, session):
    if not settings.RENDEZVOUS_DATABASE:
        return JsonResponse({"error": "Device binding is unavailable"}, status=404)
    body = binding_request(request)
    if body is None:
        return JsonResponse({"error": "Invalid device registration"}, status=400)
    device_id = body["id"]
    challenge_token = body.get("challenge")
    signature = body.get("signature")
    if not isinstance(challenge_token, str) or not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,512}", challenge_token):
        return JsonResponse({"error": "Invalid device registration"}, status=400)
    if not isinstance(signature, str) or not re.fullmatch(r"[0-9a-f]{128}", signature):
        return JsonResponse({"error": "Invalid device registration"}, status=400)
    try:
        claim = signing.loads(challenge_token, salt=SALT, max_age=120)
        if claim["session"] != session.pk or claim["id"] != device_id:
            raise signing.BadSignature
    except signing.BadSignature:
        return JsonResponse({"error": "Invalid device registration"}, status=403)

    try:
        key = registered_key(device_id)
    except sqlite3.Error:
        LOGGER.exception("Unable to read the rendezvous registration database")
        return JsonResponse({"error": "Device binding is unavailable"}, status=503)
    if key is None:
        return JsonResponse({"error": "Device has not registered with the ID server"}, status=409)
    try:
        Ed25519PublicKey.from_public_bytes(key).verify(
            bytes.fromhex(signature), DOMAIN + challenge_token.encode("ascii")
        )
    except (InvalidSignature, ValueError):
        return JsonResponse({"error": "Invalid device registration"}, status=403)

    name = body.get("name")
    platform = body.get("os")
    device, _ = Device.objects.get_or_create(
        rustdesk_id=device_id,
        defaults={
            "owner": session.user,
            "name": (name.strip()[:100] or device_id) if isinstance(name, str) else device_id,
            "platform": platform if platform in ("linux", "windows", "macos", "android", "ios") else "",
        },
    )
    if device.owner_id != session.user_id:
        return JsonResponse({"error": "Device is already assigned to another account"}, status=409)
    return JsonResponse({"id": device.rustdesk_id})
