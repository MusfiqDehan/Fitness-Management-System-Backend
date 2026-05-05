from django.contrib import admin
from django_tenants.admin import TenantAdminMixin

from .models import Tenant, Domain, Invitation, EmailQueue, TenantAuditLog


class DomainInline(admin.TabularInline):
    model = Domain
    extra = 1


@admin.register(Tenant)
class TenantAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = ['name', 'schema_name', 'slug', 'status', 'plan', 'owner_email', 'created_at']
    list_filter = ['status', 'plan', 'is_trial']
    search_fields = ['name', 'slug', 'code', 'owner_email', 'billing_email']
    readonly_fields = ['schema_name', 'created_at', 'updated_at']
    inlines = [DomainInline]


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ['domain', 'tenant', 'is_primary']
    list_filter = ['is_primary']
    search_fields = ['domain', 'tenant__name']


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ['email', 'invitee_full_name', 'tenant', 'token_type', 'expires_at', 'used_at', 'created_at']
    list_filter = ['token_type', 'created_at']
    search_fields = ['email', 'invitee_full_name', 'tenant__name', 'subdomain', 'company_name']
    readonly_fields = ['token_hash', 'created_at']


@admin.register(EmailQueue)
class EmailQueueAdmin(admin.ModelAdmin):
    list_display = ['to_email', 'purpose', 'status', 'attempts', 'sent_at', 'created_at']
    list_filter = ['purpose', 'status']
    search_fields = ['to_email', 'subject', 'tenant__name']


@admin.register(TenantAuditLog)
class TenantAuditLogAdmin(admin.ModelAdmin):
    list_display = ['action', 'tenant', 'actor_email', 'target_type', 'target_id', 'created_at']
    list_filter = ['action', 'created_at']
    search_fields = ['actor_email', 'target_type', 'target_id', 'tenant__name']
