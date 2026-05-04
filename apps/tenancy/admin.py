from django.contrib import admin
from django_tenants.admin import TenantAdminMixin

from .models import Tenant, Domain


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
