"""Serializers for tenant-scoped RBAC API."""
from rest_framework import serializers

from utils.query_optimization import prefetched_relation_count

from .models import Role, RolePermission, UserRole


class RolePermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = RolePermission
        fields = ["id", "feature_key", "permission_level"]


class RoleSerializer(serializers.ModelSerializer):
    permissions = RolePermissionSerializer(many=True, read_only=True)
    user_count = serializers.SerializerMethodField()

    class Meta:
        model = Role
        fields = [
            "id", "name", "slug", "description", "is_system", "color",
            "permissions", "user_count", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "is_system", "created_at", "updated_at"]

    def get_user_count(self, obj):
        return prefetched_relation_count(obj, "user_assignments")


class RolePermissionsBulkSerializer(serializers.Serializer):
    """PUT /roles/{id}/permissions/ — replace permissions atomically."""
    permissions = serializers.ListField(child=serializers.DictField())

    def validate_permissions(self, value):
        valid_levels = {"none", "view", "edit", "full"}
        for entry in value:
            if "feature_key" not in entry or "permission_level" not in entry:
                raise serializers.ValidationError(
                    "Each entry needs feature_key and permission_level."
                )
            if entry["permission_level"] not in valid_levels:
                raise serializers.ValidationError(
                    f"Invalid permission_level: {entry['permission_level']}"
                )
        return value


class UserRoleSerializer(serializers.ModelSerializer):
    role_name = serializers.CharField(source="role.name", read_only=True)
    role_slug = serializers.CharField(source="role.slug", read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True, default=None)

    class Meta:
        model = UserRole
        fields = [
            "id", "user_id", "user_email",
            "role", "role_name", "role_slug",
            "branch", "branch_name",
            "assigned_at", "assigned_by_email",
        ]
        read_only_fields = ["id", "assigned_at", "assigned_by_email"]
