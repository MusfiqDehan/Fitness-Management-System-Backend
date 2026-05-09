"""DRF permission classes for tenant-scoped RBAC."""
from rest_framework.permissions import BasePermission

from apps.tenancy.models import PERMISSION_HIERARCHY

from .utils import get_user_permission_level, user_can


class HasFeaturePermission(BasePermission):
    """Factory permission: requires (feature_key, required_level) on current tenant.

    Usage:

        permission_classes = [HasFeaturePermission.require("members", "edit")]
    """

    feature_key = ""
    required_level = "view"

    @classmethod
    def require(cls, feature_key: str, level: str = "view"):
        if level not in PERMISSION_HIERARCHY:
            raise ValueError(f"Invalid permission level: {level}")

        class _Bound(cls):
            pass

        _Bound.feature_key = feature_key
        _Bound.required_level = level
        _Bound.__name__ = f"HasFeature_{feature_key}_{level}"
        return _Bound

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        return user_can(user, self.feature_key, self.required_level)


class HasFeatureMethodPermission(BasePermission):
    """Feature permission that maps HTTP methods to view/edit levels.

    Views set ``feature_key``. Safe methods require ``view`` by default;
    mutating methods require ``edit`` by default. A view can override
    ``method_permission_map`` or ``write_level`` for special cases.
    """

    safe_methods = {"GET", "HEAD", "OPTIONS"}

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False

        feature_key = getattr(view, "feature_key", "")
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
        return any(user_can(user, key, required_level) for key in feature_keys)


class IsRoleAdmin(BasePermission):
    """Allow only users with `permissions` feature edit-level (manage roles)."""

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if user.is_superuser or user.is_staff or getattr(user, "role", "") == "admin":
            return True
        actual = get_user_permission_level(user, "permissions")
        return PERMISSION_HIERARCHY.get(actual, 0) >= PERMISSION_HIERARCHY.get("edit", 0)
