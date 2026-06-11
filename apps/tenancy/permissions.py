"""DRF permission classes for the tenancy app.

These cover the **platform team RBAC** (public schema only).
Tenant-scoped RBAC permissions live in `apps.access.permissions`.
"""
from django.db import connection
from django_tenants.utils import get_public_schema_name
from rest_framework.permissions import BasePermission

from .constants import PLATFORM_MODULES
from .models import (
    PERMISSION_HIERARCHY,
    PlatformRolePermission,
    PlatformUserRole,
)
from utils.cache_helpers import (
    PLATFORM_PERMISSION_TTL,
    get_cached_value,
    platform_permission_map_key,
)


# ---------------------------------------------------------------
# Helpers (also re-exported for legacy imports in views.py)
# ---------------------------------------------------------------
def is_superadmin(user):
    return bool(
        user
        and user.is_authenticated
        and (user.is_superuser or getattr(user, "role", "") == "superuser")
    )


def is_public_schema_request(request):
    request_tenant = getattr(request, "tenant", None)
    request_schema = getattr(request_tenant, "schema_name", None) or connection.schema_name
    return request_schema == get_public_schema_name()


def is_public_platform_user(user):
    public_schema = get_public_schema_name()
    user_tenant_schema = getattr(getattr(user, "tenant", None), "schema_name", None)
    # Public-schema user (tenant=None) OR user explicitly attached to public schema
    if not (user and user.is_authenticated):
        return False
    if getattr(user, "tenant_id", None) is None:
        return True
    return user_tenant_schema == public_schema


def _compute_platform_user_permission_map(user) -> dict[str, str]:
    role_ids = list(
        PlatformUserRole.objects.filter(user=user).values_list("role_id", flat=True)
    )
    if not role_ids:
        return {}
    aggregate: dict[str, str] = {}
    for module_key, level in PlatformRolePermission.objects.filter(
        role_id__in=role_ids
    ).values_list("module_key", "permission_level"):
        current = aggregate.get(module_key)
        if current is None or PERMISSION_HIERARCHY.get(level, 0) > PERMISSION_HIERARCHY.get(
            current, 0
        ):
            aggregate[module_key] = level
    return aggregate


def get_platform_user_permission_map(user) -> dict[str, str]:
    if not (user and user.is_authenticated):
        return {}
    if is_superadmin(user):
        return {module: "full" for module in PLATFORM_MODULES}
    return get_cached_value(
        platform_permission_map_key(user.id),
        PLATFORM_PERMISSION_TTL,
        lambda: _compute_platform_user_permission_map(user),
    )


def get_platform_user_permission_level(user, module_key):
    """Return the highest permission level a user has across all platform roles."""
    if not (user and user.is_authenticated):
        return "none"
    if is_superadmin(user):
        return "full"
    return get_platform_user_permission_map(user).get(module_key, "none")


# ---------------------------------------------------------------
# Permission classes
# ---------------------------------------------------------------
class IsPlatformSuperAdmin(BasePermission):
    """Allow only platform superadmins (is_superuser or role=superuser)."""

    def has_permission(self, request, view):
        return is_public_schema_request(request) and is_superadmin(request.user)


class IsPlatformFeaturePermission(BasePermission):
    """Factory-style permission: requires a specific platform module level.

    Usage on a view:

        permission_classes = [IsPlatformFeaturePermission.require("platform.tenants", "view")]

    Or with the convenience subclass `RequirePlatformPermission`.
    """

    module_key = ""
    required_level = "view"

    @classmethod
    def require(cls, module_key, level="view"):
        if module_key not in PLATFORM_MODULES:
            raise ValueError(f"Unknown platform module: {module_key}")
        if level not in PERMISSION_HIERARCHY:
            raise ValueError(f"Invalid level: {level}")

        class _Bound(cls):
            pass

        _Bound.module_key = module_key
        _Bound.required_level = level
        _Bound.__name__ = f"RequirePlatform_{module_key}_{level}"
        return _Bound

    def has_permission(self, request, view):
        if not is_public_schema_request(request):
            return False
        if not (request.user and request.user.is_authenticated):
            return False
        if is_superadmin(request.user):
            return True
        actual = get_platform_user_permission_level(request.user, self.module_key)
        return PERMISSION_HIERARCHY.get(actual, 0) >= PERMISSION_HIERARCHY.get(
            self.required_level, 0
        )
