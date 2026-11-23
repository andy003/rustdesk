import json
import secrets
from datetime import timedelta
from functools import wraps
from hashlib import sha256

from django.contrib.auth import authenticate
from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_safe

from .models import ClientSession, Device


def user_payload(user):
    return {
        "name": user.get_username(),
        "display_name": user.get_full_name(),
        "status": 1,
        "require_device_password": True,
        "device_binding": bool(settings.RENDEZVOUS_DATABASE),
        "api_only_token": True,
    }


def token_hash(token):
    return sha256(token.encode("ascii")).hexdigest()


def session_is_current(session):
    return (
        session.user.is_active
        and not session.user.is_staff
        and session.expires_at > timezone.now()
        and constant_time_compare(session.password_state, session.user.get_session_auth_hash())
    )


def client_session_required(view):
    @wraps(view)
    @never_cache
    def authenticated(request):
        scheme, _, token = request.headers.get("Authorization", "").partition(" ")
        if scheme.lower() == "bearer" and len(token) == 43 and token.isascii():
            session = ClientSession.objects.select_related("user").filter(
                token_hash=token_hash(token),
                expires_at__gt=timezone.now(),
                user__is_active=True,
                user__is_staff=False,
            ).first()
            if session and session_is_current(session):
                return view(request, session)
        return JsonResponse({"error": "Login required"}, status=401)

    return authenticated


@require_safe
def login_options(request):
    return JsonResponse([], safe=False)


@csrf_exempt
@never_cache
@require_POST
def login(request):
    try:
        body = json.loads(request.body)
    except (ValueError, RecursionError):
        return JsonResponse({"error": "Invalid login request"}, status=400)
    if not isinstance(body, dict) or body.get("type") != "account":
        return JsonResponse({"error": "Invalid login request"}, status=400)

    username = body.get("username")
    password = body.get("password")
    if not (isinstance(username, str) and 0 < len(username) <= 150):
        return JsonResponse({"error": "Invalid login request"}, status=400)
    if not (isinstance(password, str) and 0 < len(password) <= 4096):
        return JsonResponse({"error": "Invalid login request"}, status=400)

    try:
        user = authenticate(request, username=username, password=password)
    except UnicodeError:
        return JsonResponse({"error": "Invalid login request"}, status=400)
    if user is None or user.is_staff:
        return JsonResponse({"error": "Incorrect username or password."}, status=401)

    return issue_client_session(user)


def issue_client_session(user):
    now = timezone.now()
    ClientSession.objects.filter(user=user, expires_at__lte=now).delete()
    token = secrets.token_urlsafe(32)
    ClientSession.objects.create(
        user=user,
        token_hash=token_hash(token),
        password_state=user.get_session_auth_hash(),
        expires_at=now + timedelta(days=7),
    )
    response = {
        "type": "access_token",
        "access_token": token,
        "user": user_payload(user),
    }
    if settings.MANAGED_NETWORK:
        response["managed_network"] = settings.MANAGED_NETWORK
    return JsonResponse(response)


@csrf_exempt
@require_POST
@client_session_required
def current_user(request, session):
    response = user_payload(session.user)
    if settings.MANAGED_NETWORK:
        response["managed_network"] = settings.MANAGED_NETWORK
    return JsonResponse(response)


@csrf_exempt
@require_POST
@client_session_required
def logout(request, session):
    session.delete()
    return JsonResponse({})


@require_safe
@client_session_required
def users(request, session):
    return JsonResponse({"total": 1, "data": [user_payload(session.user)]})


@require_safe
@client_session_required
def device_groups(request, session):
    return JsonResponse({"total": 0, "data": []})


@require_safe
@client_session_required
def peers(request, session):
    try:
        page = int(request.GET.get("current", "1"))
        page_size = int(request.GET.get("pageSize", "100"))
        if page < 1 or not 1 <= page_size <= 100:
            raise ValueError
    except ValueError:
        return JsonResponse({"error": "Invalid page"}, status=400)

    devices = Device.objects.filter(owner=session.user)
    total = devices.count()
    offset = (page - 1) * page_size
    page_devices = devices[offset : offset + page_size] if offset < total else []
    return JsonResponse({
        "total": total,
        "data": [
            {
                "id": device.rustdesk_id,
                "info": {"device_name": device.name, "os": device.platform},
                "status": 1,
                "user_name": session.user.get_username(),
            }
            for device in page_devices
        ],
    })


@require_safe
@client_session_required
def empty_address_book(request, session):
    return JsonResponse(None, safe=False)
