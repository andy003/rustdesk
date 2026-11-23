import json
import re
import secrets
from datetime import timedelta
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, build_opener

from django.conf import settings
from django.contrib.auth.hashers import check_password
from django.db import IntegrityError, transaction
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .client_api import (
    client_session_required,
    issue_client_session,
    session_is_current,
    token_hash,
)
from .models import ClientSession, WechatIdentity, WechatLoginAttempt

LIFETIME_SECONDS = 300
TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")
OPAQUE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
Status = WechatLoginAttempt.Status


def error(message, status):
    return JsonResponse({"error": message}, status=status)


@never_cache
@require_GET
def availability(request):
    return JsonResponse({"enabled": settings.WECHAT_ENABLED})


def begin(link_session=None):
    if not settings.WECHAT_ENABLED:
        return error("WeChat sign-in is unavailable", 404)
    now = timezone.now()
    WechatLoginAttempt.objects.filter(expires_at__lte=now).delete()
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(32)
    WechatLoginAttempt.objects.create(
        state_hash=token_hash(state),
        verifier_hash=token_hash(verifier),
        app_id=settings.WECHAT_APP_ID,
        link_session=link_session,
        expires_at=now + timedelta(seconds=LIFETIME_SECONDS),
    )
    query = urlencode({
        "appid": settings.WECHAT_APP_ID,
        "redirect_uri": settings.WECHAT_CALLBACK_URL,
        "response_type": "code",
        "scope": "snsapi_login",
        "state": state,
    })
    return JsonResponse({
        "url": f"https://open.weixin.qq.com/connect/qrconnect?{query}#wechat_redirect",
        "verifier": verifier,
        "expires_in": LIFETIME_SECONDS,
    })


@csrf_exempt
@never_cache
@require_POST
def start(request):
    return begin()


@csrf_exempt
@require_POST
@client_session_required
def link(request, session):
    if not settings.WECHAT_ENABLED:
        return error("WeChat sign-in is unavailable", 404)
    try:
        body = json.loads(request.body)
        password = body.get("password") if isinstance(body, dict) else None
        if not isinstance(password, str) or not 0 < len(password) <= 4096:
            return error("Incorrect username or password.", 401)
        if not check_password(password, session.user.password):
            return error("Incorrect username or password.", 401)
    except (ValueError, RecursionError):
        return error("Incorrect username or password.", 401)
    return begin(session)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def exchange_code(code):
    query = urlencode({
        "appid": settings.WECHAT_APP_ID,
        "secret": settings.WECHAT_APP_SECRET,
        "code": code,
        "grant_type": "authorization_code",
    })
    try:
        with build_opener(NoRedirect()).open(
            f"https://api.weixin.qq.com/sns/oauth2/access_token?{query}", timeout=6
        ) as response:
            data = json.loads(response.read(16384))
    except (OSError, ValueError, RecursionError):
        return None
    if not isinstance(data, dict) or data.get("errcode"):
        return None
    open_id = data.get("openid")
    scope = data.get("scope")
    if isinstance(open_id, str) and OPAQUE_ID.fullmatch(open_id):
        if isinstance(scope, str) and "snsapi_login" in scope.split(","):
            return open_id
    return None


def callback_result(approved):
    message = "微信授权已完成。请返回 RustDesk。" if approved else "授权未完成。请返回 RustDesk 重试。"
    return HttpResponse(
        f'<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        f'<title>RustDesk</title><main><h1>RustDesk</h1><p>{message}</p></main></html>',
        status=200 if approved else 400,
        headers={"Referrer-Policy": "no-referrer"},
    )


@never_cache
@require_GET
def callback(request):
    state = request.GET.get("state", "")
    if not settings.WECHAT_ENABLED or not TOKEN.fullmatch(state):
        return callback_result(False)
    attempt = WechatLoginAttempt.objects.filter(
        state_hash=token_hash(state),
        app_id=settings.WECHAT_APP_ID,
        expires_at__gt=timezone.now(),
    )
    if not attempt.filter(status=Status.PENDING).update(status=Status.VERIFYING):
        return callback_result(False)
    code = request.GET.get("code", "")
    open_id = exchange_code(code) if OPAQUE_ID.fullmatch(code) else None
    approved = bool(attempt.filter(expires_at__gt=timezone.now()).update(
        status=Status.APPROVED if open_id else Status.FAILED,
        open_id=open_id or "",
    ) and open_id)
    return callback_result(approved)


def finish_link(attempt):
    session = ClientSession.objects.select_related("user").filter(pk=attempt.link_session_id).first()
    if not session or not session_is_current(session):
        return error("Login required", 401)
    try:
        identity, _ = WechatIdentity.objects.get_or_create(
            user=session.user,
            defaults={"app_id": attempt.app_id, "open_id": attempt.open_id},
        )
    except IntegrityError:
        return error("WeChat is already linked to an account", 409)
    if (identity.app_id, identity.open_id) != (attempt.app_id, attempt.open_id):
        return error("WeChat is already linked to an account", 409)
    return JsonResponse({"status": "linked"})


@csrf_exempt
@never_cache
@require_POST
def poll(request):
    scheme, _, verifier = request.headers.get("Authorization", "").partition(" ")
    if not settings.WECHAT_ENABLED or scheme.lower() != "bearer" or not TOKEN.fullmatch(verifier):
        return error("WeChat sign-in is unavailable", 404)
    active = WechatLoginAttempt.objects.filter(
        verifier_hash=token_hash(verifier),
        app_id=settings.WECHAT_APP_ID,
        expires_at__gt=timezone.now(),
    )
    attempt = active.first()
    if not attempt or attempt.status == Status.USED:
        return error("WeChat request expired", 410)
    if attempt.status in (Status.PENDING, Status.VERIFYING):
        return JsonResponse({"status": "pending"})
    if attempt.status != Status.APPROVED:
        return error("WeChat authorization failed", 403)
    with transaction.atomic():
        if not active.filter(status=Status.APPROVED, expires_at__gt=timezone.now()).update(
            status=Status.USED, open_id=""
        ):
            return error("WeChat request expired", 410)
        if attempt.link_session_id:
            return finish_link(attempt)
        identity = WechatIdentity.objects.select_related("user").filter(
            app_id=attempt.app_id, open_id=attempt.open_id,
            user__is_active=True, user__is_staff=False,
        ).first()
        if not identity:
            return error("Link WeChat to a client account first", 403)
        return issue_client_session(identity.user)
