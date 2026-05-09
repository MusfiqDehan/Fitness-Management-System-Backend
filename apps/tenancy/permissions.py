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


def get_platform_user_permission_level(user, module_key):
    """Return the highest permission level a user has across all platform roles."""
    if not (user and user.is_authenticated):
        return "none"
    if is_superadmin(user):
        return "full"
    role_ids = PlatformUserRole.objects.filter(user=user).values_list("role_id", flat=True)
    if not role_ids:
        return "none"
    levels = PlatformRolePermission.objects.filter(
        role_id__in=list(role_ids), module_key=module_key
    ).values_list("permission_level", flat=True)
    if not levels:
        return "none"
    return max(levels, key=lambda lv: PERMISSION_HIERARCHY.get(lv, 0))


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
