"""Serializers for RBAC, packages, and feature flags (Phases 0+1).

Kept separate from the existing `serializers.py` to avoid bloat.
"""
from rest_framework import serializers

from .constants import PLATFORM_MODULES
from .models import (
    Feature,
    PlatformPackage,
    PlatformPackageFeature,
    PlatformRole,
    PlatformRolePermission,
    PlatformUserRole,
    TenantFeatureFlag,
)


# ---------------------------------------------------------------
# Platform RBAC
# ---------------------------------------------------------------
class PlatformRolePermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformRolePermission
        fields = ["id", "module_key", "permission_level"]


class PlatformRoleSerializer(serializers.ModelSerializer):
    permissions = PlatformRolePermissionSerializer(many=True, read_only=True)
    user_count = serializers.SerializerMethodField()

    class Meta:
        model = PlatformRole
        fields = [
            "id", "name", "slug", "description", "is_system", "color",
            "permissions", "user_count", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "is_system", "created_at", "updated_at"]

    def get_user_count(self, obj):
        return obj.user_assignments.count()


class PlatformRolePermissionsBulkSerializer(serializers.Serializer):
    """Bulk update payload for PUT /roles/{id}/permissions/."""
    permissions = serializers.ListField(
        child=serializers.DictField(child=serializers.CharField())
    )

    def validate_permissions(self, value):
        valid_levels = {"none", "view", "edit", "full"}
        for entry in value:
            if "module_key" not in entry or "permission_level" not in entry:
                raise serializers.ValidationError(
                    "Each entry needs module_key and permission_level."
                )
            if entry["module_key"] not in PLATFORM_MODULES:
                raise serializers.ValidationError(
                    f"Unknown module_key: {entry['module_key']}"
                )
            if entry["permission_level"] not in valid_levels:
                raise serializers.ValidationError(
                    f"Invalid permission_level: {entry['permission_level']}"
                )
        return value


class PlatformUserRoleSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True)
    user_full_name = serializers.CharField(source="user.full_name", read_only=True)
    role_name = serializers.CharField(source="role.name", read_only=True)
    role_slug = serializers.CharField(source="role.slug", read_only=True)

    class Meta:
        model = PlatformUserRole
        fields = [
            "id", "user", "user_email", "user_full_name",
            "role", "role_name", "role_slug",
            "assigned_at", "assigned_by",
        ]
        read_only_fields = ["id", "assigned_at", "assigned_by"]


# ---------------------------------------------------------------
# Feature Registry
# ---------------------------------------------------------------
class FeatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = Feature
        fields = [
            "id", "key", "name", "description", "parent",
            "is_system", "sort_order", "created_at",
        ]
        read_only_fields = ["id", "created_at"]


# ---------------------------------------------------------------
# Platform Packages
# ---------------------------------------------------------------
class PlatformPackageFeatureSerializer(serializers.ModelSerializer):
    feature_key = serializers.CharField(source="feature.key", read_only=True)
    feature_name = serializers.CharField(source="feature.name", read_only=True)

    class Meta:
        model = PlatformPackageFeature
        fields = ["id", "feature", "feature_key", "feature_name", "is_enabled"]


class PlatformPackageSerializer(serializers.ModelSerializer):
    features = PlatformPackageFeatureSerializer(
        source="package_features", many=True, read_only=True
    )

    class Meta:
        model = PlatformPackage
        fields = [
            "id", "slug", "name", "description",
            "price_monthly", "price_yearly",
            "max_users", "max_branches", "trial_days",
            "is_active", "is_public", "sort_order", "highlight",
            "features",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class PublicPlatformPackageSerializer(serializers.ModelSerializer):
    """Public-facing package serializer used on the landing page."""
    feature_names = serializers.SerializerMethodField()

    class Meta:
        model = PlatformPackage
        fields = [
            "id", "slug", "name", "description",
            "price_monthly", "price_yearly",
            "max_users", "max_branches", "trial_days",
            "highlight", "sort_order",
            "feature_names",
        ]

    def get_feature_names(self, obj):
        return list(
            obj.package_features.filter(is_enabled=True)
            .order_by("feature__sort_order")
            .values_list("feature__name", flat=True)
        )


class PlatformPackageFeatureBulkSerializer(serializers.Serializer):
    """PUT /packages/{id}/features/ — replace package feature mapping."""
    feature_ids = serializers.ListField(child=serializers.IntegerField())


# ---------------------------------------------------------------
# Tenant Feature Flags (superadmin override management)
# ---------------------------------------------------------------
class TenantFeatureFlagSerializer(serializers.ModelSerializer):
    feature_key = serializers.CharField(source="feature.key", read_only=True)
    feature_name = serializers.CharField(source="feature.name", read_only=True)
    is_effectively_enabled = serializers.BooleanField(read_only=True)

    class Meta:
        model = TenantFeatureFlag
        fields = [
            "id", "tenant", "feature", "feature_key", "feature_name",
            "is_enabled", "source", "grace_until",
            "is_effectively_enabled", "updated_at", "updated_by_email",
        ]
        read_only_fields = ["id", "tenant", "feature", "updated_at"]


class TenantFeatureFlagBulkUpdateSerializer(serializers.Serializer):
    """PUT /tenants/{id}/features/ — superadmin bulk override."""
    overrides = serializers.ListField(child=serializers.DictField())

    def validate_overrides(self, value):
        for entry in value:
            if "feature_key" not in entry or "is_enabled" not in entry:
                raise serializers.ValidationError(
                    "Each override needs feature_key and is_enabled."
                )
        return value
