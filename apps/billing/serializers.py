"""Serializers for the platform admin billing/packages management APIs.

These wrap the canonical models that live in `apps.tenancy` (public schema):
- Feature
- PlatformPackage
- PlatformPackageFeature

Kept inside the billing app so the platform admin's "Packages" section has
its own clean, focused API surface (separate from the broader RBAC views).
"""
from rest_framework import serializers

from apps.tenancy.models import (
    Feature,
    PlatformPackage,
    PlatformPackageFeature,
)


class FeatureSerializer(serializers.ModelSerializer):
    """Read-only feature row used by the package editor UI."""

    class Meta:
        model = Feature
        fields = [
            "id",
            "key",
            "name",
            "description",
            "parent",
            "is_system",
            "sort_order",
        ]
        read_only_fields = fields


class PackageFeatureSerializer(serializers.ModelSerializer):
    feature_key = serializers.CharField(source="feature.key", read_only=True)
    feature_name = serializers.CharField(source="feature.name", read_only=True)

    class Meta:
        model = PlatformPackageFeature
        fields = ["id", "feature", "feature_key", "feature_name", "is_enabled"]


class PackageSerializer(serializers.ModelSerializer):
    """Read/write serializer for a `PlatformPackage` plus enabled feature ids."""

    features = PackageFeatureSerializer(
        source="package_features", many=True, read_only=True
    )
    feature_ids = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False
    )

    class Meta:
        model = PlatformPackage
        fields = [
            "id",
            "slug",
            "name",
            "description",
            "price_monthly",
            "price_yearly",
            "max_users",
            "max_branches",
            "trial_days",
            "is_active",
            "is_public",
            "sort_order",
            "highlight",
            "features",
            "feature_ids",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def _sync_features(self, package: PlatformPackage, feature_ids):
        wanted = set(feature_ids or [])
        existing = {
            pf.feature_id: pf
            for pf in PlatformPackageFeature.objects.filter(package=package)
        }
        for fid in wanted:
            pf = existing.get(fid)
            if pf is None:
                PlatformPackageFeature.objects.create(
                    package=package, feature_id=fid, is_enabled=True
                )
            elif not pf.is_enabled:
                pf.is_enabled = True
                pf.save(update_fields=["is_enabled"])
        for fid, pf in existing.items():
            if fid not in wanted and pf.is_enabled:
                pf.is_enabled = False
                pf.save(update_fields=["is_enabled"])

    def create(self, validated_data):
        feature_ids = validated_data.pop("feature_ids", None)
        package = super().create(validated_data)
        if feature_ids is not None:
            self._sync_features(package, feature_ids)
        return package

    def update(self, instance, validated_data):
        feature_ids = validated_data.pop("feature_ids", None)
        package = super().update(instance, validated_data)
        if feature_ids is not None:
            self._sync_features(package, feature_ids)
        return package


class PackageFeatureBulkSerializer(serializers.Serializer):
    """PUT /billing/packages/{id}/features/ — replace package feature mapping."""

    feature_ids = serializers.ListField(child=serializers.IntegerField())
