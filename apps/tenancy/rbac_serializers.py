"""Serializers for RBAC, packages, and feature flags (Phases 0+1).

Kept separate from the existing `serializers.py` to avoid bloat.
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from rest_framework import serializers

from .constants import PLATFORM_MODULES
from .models import (
    Feature,
    PlatformPackage,
    PlatformPackageFeature,
    PlatformSettings,
    PlatformPricingConfig,
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
            "max_users", "max_branches",
            "max_members_per_branch", "max_trainers_per_branch",
            "trial_days",
            "is_active", "is_public", "sort_order", "highlight",
            "badge_label", "cta_label", "cta_url",
            "setup_fee", "original_setup_fee",
            "original_price_monthly", "original_price_yearly",
            "included_items", "yearly_discount_percent",
            "price_custom_label", "price_period_label",
            "features",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class PublicPlatformPackageSerializer(serializers.ModelSerializer):
    """Public-facing package serializer used on the landing page."""

    currency = serializers.SerializerMethodField()
    price_monthly = serializers.SerializerMethodField()
    price_yearly = serializers.SerializerMethodField()
    setup_fee = serializers.SerializerMethodField()
    original_setup_fee = serializers.SerializerMethodField()
    original_price_monthly = serializers.SerializerMethodField()
    original_price_yearly = serializers.SerializerMethodField()
    feature_names = serializers.SerializerMethodField()

    class Meta:
        model = PlatformPackage
        fields = [
            "id", "slug", "name", "description",
            "currency",
            "price_monthly", "price_yearly",
            "max_users", "max_branches",
            "max_members_per_branch", "max_trainers_per_branch",
            "trial_days",
            "highlight", "sort_order",
            "badge_label", "cta_label", "cta_url",
            "setup_fee", "original_setup_fee",
            "original_price_monthly", "original_price_yearly",
            "included_items", "yearly_discount_percent",
            "price_custom_label", "price_period_label",
            "feature_names",
        ]

    def _get_platform_settings(self):
        if not hasattr(self, "_platform_settings_cache"):
            self._platform_settings_cache = PlatformSettings.objects.filter(pk=1).first()
        return self._platform_settings_cache

    def _get_display_currency(self) -> str:
        if hasattr(self, "_display_currency_cache"):
            return self._display_currency_cache

        settings = self._get_platform_settings()
        if settings and settings.default_currency:
            self._display_currency_cache = str(settings.default_currency).upper()
        else:
            # Fallback to base currency when no default currency is configured.
            self._display_currency_cache = "USD"

        return self._display_currency_cache

    def _get_rate_matrix(self):
        if hasattr(self, "_rate_matrix_cache"):
            return self._rate_matrix_cache

        matrix = {"USD": Decimal("1.0000")}
        settings = self._get_platform_settings()
        if settings and settings.enable_currency_conversion:
            try:
                matrix["BDT"] = Decimal(str(settings.usd_to_bdt_rate))
            except (TypeError, ValueError, InvalidOperation):
                matrix["BDT"] = Decimal("120.0000")

            for code, rate in (settings.exchange_rates or {}).items():
                try:
                    matrix[str(code).upper()] = Decimal(str(rate))
                except (TypeError, ValueError, InvalidOperation):
                    continue

        self._rate_matrix_cache = matrix
        return matrix

    def _convert_from_usd(self, value):
        if value in (None, ""):
            return None

        try:
            amount = Decimal(str(value))
        except (TypeError, ValueError, InvalidOperation):
            return None

        display_currency = self._get_display_currency()
        if display_currency == "USD":
            return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        rate = self._get_rate_matrix().get(display_currency)
        if rate is None:
            return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        return (amount * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def _serialize_amount(self, value):
        converted = self._convert_from_usd(value)
        if converted is None:
            return None
        return f"{converted:.2f}"

    def get_currency(self, obj):
        return self._get_display_currency()

    def get_price_monthly(self, obj):
        return self._serialize_amount(obj.price_monthly)

    def get_price_yearly(self, obj):
        return self._serialize_amount(obj.price_yearly)

    def get_setup_fee(self, obj):
        return self._serialize_amount(obj.setup_fee)

    def get_original_setup_fee(self, obj):
        return self._serialize_amount(obj.original_setup_fee)

    def get_original_price_monthly(self, obj):
        return self._serialize_amount(obj.original_price_monthly)

    def get_original_price_yearly(self, obj):
        return self._serialize_amount(obj.original_price_yearly)

    def get_feature_names(self, obj):
        prefetched = getattr(obj, "_prefetched_objects_cache", {}).get("package_features")
        if prefetched is not None:
            enabled = [
                pf.feature.name
                for pf in sorted(
                    prefetched,
                    key=lambda pf: (
                        0 if not pf.feature else (pf.feature.sort_order or 0),
                        "" if not pf.feature else (pf.feature.name or ""),
                    ),
                )
                if pf.is_enabled and pf.feature and pf.feature.name
            ]
            return enabled

        return list(
            obj.package_features.filter(is_enabled=True)
            .order_by("feature__sort_order")
            .values_list("feature__name", flat=True)
        )


class PlatformPricingConfigSerializer(serializers.ModelSerializer):
    """Read/write serializer for the singleton PlatformPricingConfig."""

    class Meta:
        model = PlatformPricingConfig
        fields = ["id", "default_yearly_discount_percent", "updated_at"]
        read_only_fields = ["id", "updated_at"]


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
