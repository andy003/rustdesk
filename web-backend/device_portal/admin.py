from django.contrib import admin

from .models import Device, WechatIdentity


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ("name", "rustdesk_id", "owner")
    search_fields = ("name", "rustdesk_id", "owner__username")


@admin.register(WechatIdentity)
class WechatIdentityAdmin(admin.ModelAdmin):
    list_display = ("user", "app_id")
    search_fields = ("user__username",)
    fields = readonly_fields = ("user", "app_id")

    def has_add_permission(self, request):
        return False
