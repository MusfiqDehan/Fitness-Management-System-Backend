"""Helpers for resolving tenant-scoped permissions.

These run *inside* a tenant schema. They combine:
  * `apps.tenancy.services.tenant_has_feature` — package gate
  * `apps.access.models.UserRole` / `RolePermission` — per-user gate

A user can only act on a feature if BOTH gates allow it.
"""
from django.db import connection
from django_tenants.utils import get_public_schema_name

from apps.tenancy.models import PERMISSION_HIERARCHY
from apps.tenancy.services import tenant_has_feature

from .models import RolePermission, UserRole


def is_in_tenant_schema() -> bool:
    return connection.schema_name != get_public_schema_name()


def get_user_role_ids(user) -> list[int]:
    """Return UserRole.role_id list for the given user in current schema."""
    if not (user and user.is_authenticated):
        return []
    return list(
        UserRole.objects.filter(user_id=user.id).values_list("role_id", flat=True)
    )


def get_user_permission_level(user, feature_key: str) -> str:
    """Compute the highest permission level a user has for a feature in this tenant.

    Tenant admins (is_staff or role='admin') bypass the role check
    and receive 'full'. Anonymous → 'none'.
    """
    if not (user and user.is_authenticated):
        return "none"
    # Tenant superusers / staff get full access (legacy behaviour)
    if user.is_superuser or user.is_staff or getattr(user, "role", "") == "admin":
        return "full"
    role_ids = get_user_role_ids(user)
    if not role_ids:
        return "none"
    levels = RolePermission.objects.filter(
        role_id__in=role_ids, feature_key=feature_key
    ).values_list("permission_level", flat=True)
    if not levels:
        return "none"
    return max(levels, key=lambda lv: PERMISSION_HIERARCHY.get(lv, 0))


def user_can(user, feature_key: str, required_level: str = "view") -> bool:
    """Return True if user has at least required_level on feature_key.

    Also enforces that the current tenant has the feature enabled
    (package gate). If called outside a tenant schema, returns False.
    """
    if not is_in_tenant_schema():
        return False
    # Prefer the active schema tenant over user.tenant to avoid stale assignments.
    tenant = _resolve_current_tenant() or getattr(user, "tenant", None)
    if tenant is None:
        return False
    if not tenant_has_feature(tenant, feature_key):
        return False
    actual = get_user_permission_level(user, feature_key)
    return PERMISSION_HIERARCHY.get(actual, 0) >= PERMISSION_HIERARCHY.get(
        required_level, 0
    )


def get_user_permission_map(user) -> dict[str, str]:
    """Return {feature_key: permission_level} for all roles assigned to user.

    Used by the frontend to drive UI gating after login.
    """
    if not (user and user.is_authenticated):
        return {}
    if user.is_superuser or user.is_staff or getattr(user, "role", "") == "admin":
        # Caller decides what to do; we return an empty map (frontend
        # treats "tenant_admin" flag separately).
        pass
    role_ids = get_user_role_ids(user)
    if not role_ids:
        return {}
    perms = RolePermission.objects.filter(role_id__in=role_ids).values(
        "feature_key", "permission_level"
    )
    aggregate: dict[str, str] = {}
    for p in perms:
        key = p["feature_key"]
        level = p["permission_level"]
        current = aggregate.get(key)
        if current is None or PERMISSION_HIERARCHY.get(level, 0) > PERMISSION_HIERARCHY.get(current, 0):
            aggregate[key] = level
    return aggregate


def _resolve_current_tenant():
    """Look up the Tenant matching the current connection schema."""
    from apps.tenancy.models import Tenant
    if not is_in_tenant_schema():
        return None
    return Tenant.objects.filter(schema_name=connection.schema_name).first()
