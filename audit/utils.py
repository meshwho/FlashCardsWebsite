from .models import AuditLog


def get_client_ip(request):
    if not request:
        return None

    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()

    return request.META.get("REMOTE_ADDR")


def log_action(
    *,
    user=None,
    action=AuditLog.ACTION_OTHER,
    message="",
    entity=None,
    details=None,
    request=None,
):
    entity_type = ""
    entity_id = ""

    if entity is not None:
        entity_type = entity.__class__.__name__
        entity_id = getattr(entity, "public_id", None) or getattr(entity, "id", "")

    return AuditLog.objects.create(
        user=user,
        action=action,
        message=message,
        entity_type=entity_type,
        entity_id=str(entity_id),
        details=details or {},
        ip_address=get_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "") if request else "",
    )