from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver

from .models import AuditLog
from .utils import log_action


@receiver(user_logged_in)
def audit_user_logged_in(sender, request, user, **kwargs):
    log_action(
        user=user,
        action=AuditLog.ACTION_LOGIN,
        message="User logged in",
        entity=user,
        details={
            "username": user.username,
            "email": getattr(user, "email", ""),
            "login_via": "password",
        },
        request=request,
    )


@receiver(user_logged_out)
def audit_user_logged_out(sender, request, user, **kwargs):
    if user is None:
        return

    log_action(
        user=user,
        action=AuditLog.ACTION_LOGOUT,
        message="User logged out",
        entity=user,
        details={
            "username": user.username,
            "email": getattr(user, "email", ""),
        },
        request=request,
    )