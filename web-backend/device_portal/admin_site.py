from itertools import islice

from django_otp import devices_for_user
from django_otp.admin import OTPAdminAuthenticationForm, OTPAdminSite


class PortalAdminAuthenticationForm(OTPAdminAuthenticationForm):
    def clean_otp(self, user):
        if user is not None and not self.cleaned_data.get("otp_device"):
            devices = list(islice(devices_for_user(user), 2))
            if len(devices) == 1:
                self.cleaned_data["otp_device"] = devices[0].persistent_id
        try:
            super().clean_otp(user)
        finally:
            self.fields["password"].widget.render_value = False


class PortalAdminSite(OTPAdminSite):
    login_form = PortalAdminAuthenticationForm
