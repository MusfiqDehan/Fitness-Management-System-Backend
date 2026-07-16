"""Cache invalidation hooks for model mutations."""

from django.db import connection
from django.db.models import Q
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from utils.cache_helpers import (
    bump_tenant_access_me_version,
    invalidate_domain_schema,
    invalidate_notification_count,
    invalidate_platform_settings,
    invalidate_public_branches,
    invalidate_public_branding,
    invalidate_public_packages,
    invalidate_public_pricing_config,
    invalidate_tenant_admin_notification_counts,
    invalidate_tenant_overview,
    invalidate_timezone,
    invalidate_user_permissions,
)


@receiver(post_save, sender="tenancy.PlatformPackage")
@receiver(post_delete, sender="tenancy.PlatformPackage")
def invalidate_public_packages_on_package_change(sender, **kwargs):
    invalidate_public_packages()


@receiver(post_save, sender="tenancy.PlatformPackageFeature")
@receiver(post_delete, sender="tenancy.PlatformPackageFeature")
def invalidate_public_packages_on_package_feature_change(sender, **kwargs):
    invalidate_public_packages()


@receiver(post_save, sender="tenancy.PlatformPricingConfig")
def invalidate_public_pricing_on_config_change(sender, **kwargs):
    invalidate_public_pricing_config()


@receiver(post_save, sender="tenancy.PlatformSettings")
def invalidate_platform_settings_on_save(sender, instance, update_fields=None, **kwargs):
    invalidate_platform_settings()
    if update_fields is None or "enable_custom_domains" in update_fields:
        from apps.tenancy.models import Tenant

        for schema_name in Tenant.objects.values_list("schema_name", flat=True):
            if schema_name and schema_name != "public":
                bump_tenant_access_me_version(schema_name)


@receiver(post_save, sender="tenancy.Domain")
@receiver(post_delete, sender="tenancy.Domain")
def invalidate_domain_on_change(sender, instance, **kwargs):
    invalidate_domain_schema(instance.tenant.schema_name)


@receiver(post_save, sender="tenancy.Tenant")
def invalidate_tenant_timezone_on_save(sender, instance, update_fields=None, **kwargs):
    timezone_changed = update_fields is None or "timezone" in update_fields
    custom_domain_changed = update_fields is None or "custom_domain_enabled" in update_fields
    if not timezone_changed and not custom_domain_changed:
        return
    if timezone_changed:
        invalidate_timezone(instance.schema_name)
    if custom_domain_changed:
        bump_tenant_access_me_version(instance.schema_name)


@receiver(post_save, sender="tenancy.Tenant")
@receiver(post_delete, sender="tenancy.Tenant")
def invalidate_tenant_overview_on_tenant_change(sender, **kwargs):
    invalidate_tenant_overview()


@receiver(post_save, sender="tenancy.Invitation")
@receiver(post_delete, sender="tenancy.Invitation")
def invalidate_tenant_overview_on_invitation_change(sender, **kwargs):
    invalidate_tenant_overview()


@receiver(post_save, sender="gym_branch.Branch")
@receiver(post_delete, sender="gym_branch.Branch")
def invalidate_public_branches_on_branch_change(sender, **kwargs):
    schema_name = connection.schema_name
    if schema_name and schema_name != "public":
        invalidate_public_branches(schema_name)


@receiver(post_save, sender="dashboard.GymProfile")
def invalidate_gym_profile_cache(sender, **kwargs):
    schema_name = connection.schema_name
    if schema_name and schema_name != "public":
        invalidate_public_branding(schema_name)
        invalidate_timezone(schema_name)


@receiver(post_save, sender="tenancy.PlatformGymProfile")
def invalidate_platform_gym_profile_cache(sender, **kwargs):
    schema_name = connection.schema_name or "public"
    invalidate_public_branding(schema_name)


@receiver(post_save, sender="reminder.Notification")
@receiver(post_delete, sender="reminder.Notification")
def invalidate_notification_count_on_notification_change(sender, instance, **kwargs):
    schema_name = connection.schema_name
    if not schema_name or schema_name == "public":
        return
    recipient_id = getattr(instance, "recipient_id", None)
    if recipient_id:
        invalidate_notification_count(schema_name, recipient_id)
        return
    invalidate_tenant_admin_notification_counts(schema_name)


@receiver(post_save, sender="reminder.NotificationRead")
def invalidate_notification_count_on_read(sender, instance, **kwargs):
    schema_name = connection.schema_name
    if not schema_name or schema_name == "public":
        return
    if instance.user_id:
        invalidate_notification_count(schema_name, instance.user_id)


@receiver(post_save, sender="identity.User")
def invalidate_user_permissions_on_identity_change(sender, instance, update_fields=None, **kwargs):
    tracked = {"is_staff", "is_superuser", "role"}
    if update_fields is not None and tracked.isdisjoint(update_fields):
        return
    schema_name = connection.schema_name
    if not schema_name or schema_name == "public":
        return
    invalidate_user_permissions(schema_name, instance.id)
