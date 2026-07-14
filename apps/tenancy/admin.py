from django.contrib import admin, messages
from django_tenants.admin import TenantAdminMixin
from django_tenants.utils import get_public_schema_name

from .models import Tenant, Domain, Invitation, EmailQueue, TenantAuditLog


class DomainInline(admin.TabularInline):
    model = Domain
    extra = 1


@admin.register(Tenant)
class TenantAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = [
        "name",
        "schema_name",
        "slug",
        "status",
        "plan",
        "owner_email",
        "created_at",
    ]
    list_filter = ["status", "plan", "is_trial"]
    search_fields = ["name", "slug", "code", "owner_email", "billing_email"]
    readonly_fields = ["schema_name", "created_at", "updated_at"]
    inlines = [DomainInline]

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.schema_name == get_public_schema_name():
            return False
        return super().has_delete_permission(request, obj)

    def delete_model(self, request, obj):
        """Drop the tenant PostgreSQL schema before removing the row.

        Plain deletes fail with IntegrityError: tenant-schema ``identity_user``
        rows keep a cross-schema FK to ``public.tenancy_tenant``, and Django's
        collector only sees the public schema.
        """
        if obj.schema_name == get_public_schema_name():
            messages.error(request, "The public tenant cannot be deleted.")
            return
        try:
            obj.delete(force_drop=True)
        except PermissionError as exc:
            messages.error(request, str(exc))

    def delete_queryset(self, request, queryset):
        public_name = get_public_schema_name()
        protected = queryset.filter(schema_name=public_name)
        deletable = list(queryset.exclude(schema_name=public_name))
        if protected.exists():
            messages.error(request, "Skipped deleting the public tenant.")
        for obj in deletable:
            try:
                obj.delete(force_drop=True)
            except PermissionError as exc:
                messages.error(request, str(exc))


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ["domain", "tenant", "is_primary"]
    list_filter = ["is_primary"]
    search_fields = ["domain", "tenant__name"]


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = [
        "email",
        "invitee_full_name",
        "tenant",
        "token_type",
        "expires_at",
        "used_at",
        "created_at",
    ]
    list_filter = ["token_type", "created_at"]
    search_fields = [
        "email",
        "invitee_full_name",
        "tenant__name",
        "subdomain",
        "company_name",
    ]
    readonly_fields = ["token_hash", "created_at"]


@admin.register(EmailQueue)
class EmailQueueAdmin(admin.ModelAdmin):
    list_display = [
        "to_email",
        "purpose",
        "status",
        "attempts",
        "sent_at",
        "created_at",
    ]
    list_filter = ["purpose", "status"]
    search_fields = ["to_email", "subject", "tenant__name"]


@admin.register(TenantAuditLog)
class TenantAuditLogAdmin(admin.ModelAdmin):
    list_display = [
        "action",
        "tenant",
        "actor_email",
        "target_type",
        "target_id",
        "created_at",
    ]
    list_filter = ["action", "created_at"]
    search_fields = ["actor_email", "target_type", "target_id", "tenant__name"]
