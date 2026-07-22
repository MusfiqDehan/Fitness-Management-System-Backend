"""CMS permission classes — schema-aware for public + tenant hosts."""
from rest_framework.permissions import BasePermission

from apps.access.permissions import HasFeatureMethodPermission
from apps.tenancy.models import PERMISSION_HIERARCHY
from apps.tenancy.permissions import (
    get_platform_user_permission_level,
    is_public_schema_request,
    is_superadmin,
)

# Tenant feature_key → platform module_key
TENANT_TO_PLATFORM_CMS = {
    "cms.banners": "platform.cms.banners",
    "cms.blogs": "platform.cms.blogs",
}


class IsAdminStaffOrSuperuser(BasePermission):
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and (request.user.is_superuser or request.user.is_staff)
        )


class HasCmsFeatureMethodPermission(BasePermission):
    """Authorize CMS admin views on both public and tenant schemas.

    Views set ``feature_key`` to a tenant key (``cms.banners`` / ``cms.blogs``).

    - Tenant schema: delegates to ``HasFeatureMethodPermission``.
    - Public schema: maps to ``platform.cms.*`` and checks platform RBAC
      with the same safe-method → view / mutate → edit mapping.
    """

    safe_methods = {"GET", "HEAD", "OPTIONS"}

    def has_permission(self, request, view):
        if is_public_schema_request(request):
            return self._has_platform_permission(request, view)
        return HasFeatureMethodPermission().has_permission(request, view)

    def _has_platform_permission(self, request, view) -> bool:
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if is_superadmin(user):
            return True

        feature_key = getattr(view, "feature_key", "") or ""
        feature_keys = list(getattr(view, "feature_keys", []) or [])
        if feature_key:
            feature_keys.append(feature_key)
        if not feature_keys:
            return False

        method_permission_map = getattr(view, "method_permission_map", {}) or {}
        required_level = method_permission_map.get(request.method)
        if required_level is None:
            required_level = getattr(
                view,
                "read_level" if request.method in self.safe_methods else "write_level",
                "view" if request.method in self.safe_methods else "edit",
            )

        for key in feature_keys:
            module_key = TENANT_TO_PLATFORM_CMS.get(key)
            if not module_key:
                continue
            actual = get_platform_user_permission_level(user, module_key)
            if PERMISSION_HIERARCHY.get(actual, 0) >= PERMISSION_HIERARCHY.get(
                required_level, 0
            ):
                return True
        return False
