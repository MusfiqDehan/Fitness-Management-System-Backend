"""Shared Redis cache key builders, TTL constants, and invalidation helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from django.core.cache import cache

T = TypeVar("T")

# TTL constants (seconds)
TENANT_FEATURE_TTL = 300
PERMISSION_TTL = 300
PLATFORM_PERMISSION_TTL = 600
TIMEZONE_TTL = 900
DOMAIN_TTL = 3600
PUBLIC_PACKAGE_TTL = 1800
PUBLIC_PRICING_CONFIG_TTL = 1800
PUBLIC_BRANCH_TTL = 600
PUBLIC_BRANDING_TTL = 900
PLATFORM_SETTINGS_TTL = 900
ACCESS_ME_TTL = 120
STATS_TTL = 60
TENANT_OVERVIEW_TTL = 120
NOTIFICATION_COUNT_TTL = 30


def tenant_feature_key(tenant_id: int) -> str:
    return f"tff:{tenant_id}:enabled_keys"


def permission_map_key(schema_name: str, user_id: int) -> str:
    return f"perm:{schema_name}:{user_id}:map"


def platform_permission_map_key(user_id: int) -> str:
    return f"platform:perm:{user_id}:map"


def timezone_key(schema_name: str) -> str:
    return f"tz:{schema_name}"


def domain_schema_key(schema_name: str) -> str:
    return f"domain:schema:{schema_name}"


def public_packages_key() -> str:
    return "public:packages:v1"


def public_pricing_config_key() -> str:
    return "public:pricing_config:v1"


def public_branches_key(
    schema_name: str,
    *,
    minimal: bool = False,
    homepage: bool = False,
) -> str:
    suffix = "minimal" if minimal else "full"
    if homepage:
        suffix = f"{suffix}:homepage"
    return f"tenant:{schema_name}:branches:{suffix}"


def public_branding_key(schema_name: str) -> str:
    return f"tenant:{schema_name}:branding:v1"


def platform_settings_key() -> str:
    return "platform:settings:v1"


def access_me_key(schema_name: str, user_id: int) -> str:
    version = cache.get(_tenant_access_me_version_key(schema_name), 0)
    return f"access:me:{schema_name}:{user_id}:v{version}"


def _tenant_access_me_version_key(schema_name: str) -> str:
    return f"access:me:ver:{schema_name}"


def bump_tenant_access_me_version(schema_name: str) -> None:
    key = _tenant_access_me_version_key(schema_name)
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=None)


def stats_scope_token(user, branch_filter_id=None) -> str:
    """Build a user-aware stats cache scope (branch managers != tenant admins)."""
    from utils.tenancy_helpers import get_branch_manager_scope_ids, is_tenant_admin_user

    branch = branch_filter_id or "all"
    if is_tenant_admin_user(user):
        return f"admin:{branch}"
    scope_ids = get_branch_manager_scope_ids(user)
    if scope_ids is None:
        return f"user:{user.id}:{branch}"
    joined = ",".join(str(branch_id) for branch_id in sorted(scope_ids))
    return f"bm:{user.id}:{joined}:{branch}"


def stats_key(schema_name: str, view_name: str, scope: str) -> str:
    return f"stats:{schema_name}:{view_name}:{scope}"


def tenant_overview_key() -> str:
    return "platform:tenant_overview:v1"


def notification_count_key(schema_name: str, user_id: int) -> str:
    return f"notif:count:{schema_name}:{user_id}"


def get_cached_value(key: str, ttl: int, factory: Callable[[], T]) -> T:
    """Return cached value or compute, store, and return."""
    cached = cache.get(key)
    if cached is not None:
        return cached
    value = factory()
    cache.set(key, value, ttl)
    return value


def invalidate_tenant_features(tenant_id: int) -> None:
    cache.delete(tenant_feature_key(tenant_id))
    from apps.tenancy.models import Tenant

    schema_name = (
        Tenant.objects.filter(pk=tenant_id).values_list("schema_name", flat=True).first()
    )
    if schema_name:
        bump_tenant_access_me_version(schema_name)


def invalidate_notification_count(schema_name: str, user_id: int) -> None:
    cache.delete(notification_count_key(schema_name, user_id))


def invalidate_tenant_admin_notification_counts(schema_name: str) -> None:
    from apps.identity.models import User
    from django.db.models import Q

    admin_ids = User.objects.filter(
        Q(is_staff=True) | Q(role="admin") | Q(is_superuser=True)
    ).values_list("id", flat=True)
    for user_id in admin_ids:
        invalidate_notification_count(schema_name, user_id)


def invalidate_user_permissions(schema_name: str, user_id: int) -> None:
    cache.delete(permission_map_key(schema_name, user_id))
    cache.delete(access_me_key(schema_name, user_id))
    invalidate_notification_count(schema_name, user_id)


def invalidate_role_permissions(schema_name: str, role_id: int) -> None:
    from apps.access.models import UserRole

    user_ids = UserRole.objects.filter(role_id=role_id).values_list(
        "user_id", flat=True
    )
    for user_id in user_ids:
        invalidate_user_permissions(schema_name, user_id)


def invalidate_platform_user_permissions(user_id: int) -> None:
    cache.delete(platform_permission_map_key(user_id))


def invalidate_platform_role_permissions(role_id: int) -> None:
    from apps.tenancy.models import PlatformUserRole

    user_ids = PlatformUserRole.objects.filter(role_id=role_id).values_list(
        "user_id", flat=True
    )
    for user_id in user_ids:
        invalidate_platform_user_permissions(user_id)


def invalidate_timezone(schema_name: str) -> None:
    cache.delete(timezone_key(schema_name))


def invalidate_domain_schema(schema_name: str) -> None:
    cache.delete(domain_schema_key(schema_name))


def invalidate_public_branches(schema_name: str) -> None:
    for minimal in (False, True):
        for homepage in (False, True):
            cache.delete(
                public_branches_key(
                    schema_name,
                    minimal=minimal,
                    homepage=homepage,
                )
            )


def invalidate_public_branding(schema_name: str) -> None:
    cache.delete(public_branding_key(schema_name))


def invalidate_public_packages() -> None:
    cache.delete(public_packages_key())


def invalidate_public_pricing_config() -> None:
    cache.delete(public_pricing_config_key())


def invalidate_platform_settings() -> None:
    cache.delete(platform_settings_key())
    invalidate_public_packages()


def invalidate_tenant_overview() -> None:
    cache.delete(tenant_overview_key())


def get_platform_settings_cached() -> dict[str, Any] | None:
    """Load PlatformSettings pk=1 fields from cache (public schema caller)."""

    def _load():
        from apps.tenancy.models import PlatformSettings

        row = PlatformSettings.objects.filter(pk=1).first()
        if row is None:
            return None
        return {
            "default_timezone": row.default_timezone,
            "default_currency": row.default_currency,
            "default_language": row.default_language,
            "enable_currency_conversion": row.enable_currency_conversion,
            "enable_custom_domains": row.enable_custom_domains,
            "usd_to_bdt_rate": str(row.usd_to_bdt_rate),
            "exchange_rates": row.exchange_rates or {},
        }

    return get_cached_value(platform_settings_key(), PLATFORM_SETTINGS_TTL, _load)
