import os
from base64 import b64decode
from binascii import Error as Base64Error
from pathlib import Path
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ["RUSTDESK_WEB_SECRET_KEY"]
DEVELOPMENT = os.environ.get("RUSTDESK_WEB_DEVELOPMENT") == "1"
DEBUG = DEVELOPMENT
ALLOWED_HOSTS = os.environ.get("RUSTDESK_WEB_HOSTS", "localhost,127.0.0.1").split(",")
RENDEZVOUS_DATABASE = os.environ.get("RUSTDESK_WEB_HBBS_DATABASE", "")
FORCE_SCRIPT_NAME = os.environ.get("RUSTDESK_WEB_PATH", "").rstrip("/") or None
WECHAT_APP_ID = os.environ.get("RUSTDESK_WEB_WECHAT_APP_ID", "")
WECHAT_APP_SECRET = os.environ.get("RUSTDESK_WEB_WECHAT_APP_SECRET", "")
WECHAT_CALLBACK_URL = os.environ.get("RUSTDESK_WEB_WECHAT_CALLBACK_URL", "")
if any((WECHAT_APP_ID, WECHAT_APP_SECRET, WECHAT_CALLBACK_URL)):
    callback = urlsplit(WECHAT_CALLBACK_URL)
    if not (
        WECHAT_APP_ID and WECHAT_APP_SECRET
        and callback.scheme == "https" and callback.hostname in ALLOWED_HOSTS
        and callback.netloc == callback.hostname
        and callback.path == (FORCE_SCRIPT_NAME or "") + "/api/wechat/callback"
        and not callback.query and not callback.fragment
    ):
        raise ImproperlyConfigured("WeChat login requires an AppID, AppSecret and the portal's HTTPS callback URL")
WECHAT_ENABLED = bool(WECHAT_APP_ID)

MANAGED_NETWORK = {
    "id_server": os.environ.get("RUSTDESK_WEB_ID_SERVER", ""),
    "relay_server": os.environ.get("RUSTDESK_WEB_RELAY_SERVER", ""),
    "public_key": os.environ.get("RUSTDESK_WEB_SERVER_PUBLIC_KEY", ""),
}
if any(MANAGED_NETWORK.values()):
    try:
        valid_key = len(b64decode(MANAGED_NETWORK["public_key"], validate=True)) == 32
    except Base64Error:
        valid_key = False
    if not all(MANAGED_NETWORK.values()) or not valid_key:
        raise ImproperlyConfigured("Managed networking requires both server addresses and an Ed25519 public key")
else:
    MANAGED_NETWORK = None

INSTALLED_APPS = [
    "django.contrib.admin" if DEVELOPMENT else "device_portal.admin_config.PortalAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "device_portal",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "device_portal.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("RUSTDESK_WEB_DATABASE", BASE_DIR / "db.sqlite3"),
    },
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": f"django.contrib.auth.password_validation.{validator}"}
    for validator in (
        "UserAttributeSimilarityValidator",
        "MinimumLengthValidator",
        "CommonPasswordValidator",
        "NumericPasswordValidator",
    )
]

LANGUAGE_CODE = "zh-hans"
USE_TZ = True
STATIC_URL = (FORCE_SCRIPT_NAME or "") + "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

SESSION_COOKIE_NAME = "rustdesk_portal_session"
CSRF_COOKIE_NAME = "rustdesk_portal_csrf"
SESSION_COOKIE_PATH = CSRF_COOKIE_PATH = (FORCE_SCRIPT_NAME or "") + "/"
SESSION_COOKIE_AGE = 8 * 60 * 60
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = not DEVELOPMENT
CSRF_COOKIE_HTTPONLY = True
SECURE_SSL_REDIRECT = not DEVELOPMENT
SECURE_HSTS_SECONDS = 0 if DEVELOPMENT else 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEVELOPMENT
if os.environ.get("RUSTDESK_WEB_TRUST_PROXY") == "1":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
