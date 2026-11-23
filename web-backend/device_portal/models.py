from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models


class Device(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, verbose_name="归属账号"
    )
    name = models.CharField("设备名称", max_length=100)
    platform = models.CharField("设备平台", max_length=20, blank=True)
    rustdesk_id = models.CharField(
        "RustDesk ID",
        max_length=16,
        unique=True,
        validators=[
            RegexValidator(
                r"\A(?:[0-9]{1,16}|[a-zA-Z][a-zA-Z0-9_-]{5,15})\Z",
                "请输入去掉空格的 RustDesk 数字 ID 或自定义 ID。",
            )
        ],
    )

    class Meta:
        ordering = ["name", "pk"]
        verbose_name = "设备"
        verbose_name_plural = "设备"

    def __str__(self):
        return self.name


class ClientSession(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    token_hash = models.CharField(max_length=64, unique=True)
    password_state = models.CharField(max_length=64)
    expires_at = models.DateTimeField()


class WechatIdentity(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    app_id = models.CharField(max_length=64)
    open_id = models.CharField(max_length=128)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("app_id", "open_id"), name="wechat_identity_app_open_id")
        ]
        verbose_name = "微信绑定"
        verbose_name_plural = "微信绑定"


class WechatLoginAttempt(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending"
        VERIFYING = "verifying"
        APPROVED = "approved"
        FAILED = "failed"
        USED = "used"

    state_hash = models.CharField(max_length=64, unique=True)
    verifier_hash = models.CharField(max_length=64, unique=True)
    app_id = models.CharField(max_length=64)
    link_session = models.ForeignKey(ClientSession, null=True, on_delete=models.CASCADE)
    expires_at = models.DateTimeField(db_index=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    open_id = models.CharField(max_length=128, blank=True)
