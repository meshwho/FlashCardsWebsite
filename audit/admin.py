from django.contrib import admin
from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "user",
        "action",
        "entity_type",
        "entity_id",
        "message",
        "ip_address",
    )
    list_filter = ("action", "entity_type", "created_at")
    search_fields = ("message", "entity_type", "entity_id", "user__username", "user__email")
    ordering = ("-created_at",)
    readonly_fields = (
        "user",
        "action",
        "entity_type",
        "entity_id",
        "message",
        "details",
        "ip_address",
        "user_agent",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False