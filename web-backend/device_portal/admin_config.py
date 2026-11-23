from django.contrib.admin.apps import AdminConfig


class PortalAdminConfig(AdminConfig):
    default_site = "device_portal.admin_site.PortalAdminSite"
