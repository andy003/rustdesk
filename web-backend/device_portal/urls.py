from django.contrib import admin
from django.urls import path
from django.views.generic import RedirectView

from . import client_api, device_binding, wechat

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="admin:index")),
    path("admin/", admin.site.urls),
    path("api/login-options", client_api.login_options),
    path("api/login", client_api.login),
    path("api/wechat/status", wechat.availability),
    path("api/wechat/start", wechat.start),
    path("api/wechat/link", wechat.link),
    path("api/wechat/callback", wechat.callback),
    path("api/wechat/poll", wechat.poll),
    path("api/currentUser", client_api.current_user),
    path("api/logout", client_api.logout),
    path("api/users", client_api.users),
    path("api/device-group/accessible", client_api.device_groups),
    path("api/peers", client_api.peers),
    path("api/device-binding/challenge", device_binding.challenge),
    path("api/device-binding", device_binding.bind_device),
    path("api/ab", client_api.empty_address_book),
]
