"""API views for tenant-scoped RBAC.

All endpoints run inside a tenant schema. Role-managers (users with
`permissions` feature edit-level) can manage roles and assignments.
Other authenticated users can read their own permissions via
``MyPermissionsView``.
"""
from django.db import connection, transaction
from django_tenants.utils import get_public_schema_name
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.tenancy.models import Feature, TenantFeatureFlag

from .models import Role, RolePermission, UserRole
from .permissions import IsRoleAdmin
from .serializers import (
    RolePermissionsBulkSerializer,
    RoleSerializer,
    UserRoleSerializer,
)
from .utils import get_user_permission_map


class RoleListCreateView(generics.ListCreateAPIView):
    queryset = Role.objects.all().prefetch_related("permissions", "user_assignments").order_by("id")
    serializer_class = RoleSerializer
    permission_classes = [IsRoleAdmin]
    pagination_class = None  # role list is small; return a plain array


class RoleDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Role.objects.all().prefetch_related("permissions")
    serializer_class = RoleSerializer
    permission_classes = [IsRoleAdmin]

    def perform_destroy(self, instance):
        if instance.is_system:
            from rest_framework.exceptions import ValidationError
            raise ValidationError("System roles cannot be deleted.")
        instance.delete()


class RolePermissionsView(APIView):
    """GET / PUT permissions for a specific role."""

    permission_classes = [IsRoleAdmin]

    def get(self, request, role_id):
        role = generics.get_object_or_404(Role, pk=role_id)
        return Response({
            "role_id": role.id,
            "permissions": list(role.permissions.values("feature_key", "permission_level")),
        })

    def put(self, request, role_id):
        role = generics.get_object_or_404(Role, pk=role_id)
        serializer = RolePermissionsBulkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            existing = {p.feature_key: p for p in role.permissions.all()}
            sent_keys = set()
            for entry in serializer.validated_data["permissions"]:
                key = entry["feature_key"]
                level = entry["permission_level"]
                sent_keys.add(key)
                if key in existing:
                    p = existing[key]
                    if p.permission_level != level:
                        p.permission_level = level
                        p.save(update_fields=["permission_level"])
                else:
                    RolePermission.objects.create(
                        role=role, feature_key=key, permission_level=level
                    )
            for key, p in existing.items():
                if key not in sent_keys:
                    p.delete()
        return Response({"status": "ok"})


class UserRoleListCreateView(generics.ListCreateAPIView):
    queryset = UserRole.objects.select_related("role").all().order_by("id")
    serializer_class = UserRoleSerializer
    permission_classes = [IsRoleAdmin]
    pagination_class = None  # user-role list is small; return a plain array

    def perform_create(self, serializer):
        actor_email = getattr(self.request.user, "email", "") or ""
        serializer.save(assigned_by_email=actor_email)


class UserRoleDetailView(generics.RetrieveDestroyAPIView):
    queryset = UserRole.objects.all()
    serializer_class = UserRoleSerializer
    permission_classes = [IsRoleAdmin]


class MyPermissionsView(APIView):
    """Returns the current user's permission map and tenant feature keys."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        is_tenant_admin = bool(
            user.is_superuser
            or user.is_staff
            or getattr(user, "role", "") == "admin"
        )
        permission_map = get_user_permission_map(user)
        # Resolve tenant from request first; older users can have null/stale user.tenant.
        tenant = getattr(request, "tenant", None) or getattr(user, "tenant", None)
        feature_keys: list[str] = []
        if tenant is not None and connection.schema_name != get_public_schema_name():
            flags = TenantFeatureFlag.objects.filter(tenant=tenant).select_related("feature")
            feature_keys = [f.feature.key for f in flags if f.is_effectively_enabled]
        return Response({
            "user_id": user.id,
            "email": user.email,
            "full_name": getattr(user, "full_name", "") or "",
            "role": getattr(user, "role", "") or "",
            "is_tenant_admin": is_tenant_admin,
            "permissions": permission_map,
            "enabled_features": feature_keys,
        })


class TenantFeatureCatalogView(APIView):
    """Lists all known tenant feature definitions — read-only, used by the role editor.

    Sourced directly from `apps.tenancy.feature_registry.TENANT_REGISTRY` so the
    matrix UI always reflects the canonical registry, even before
    `python manage.py sync_features` has been run against the database.
    """

    permission_classes = [IsRoleAdmin]

    def get(self, request):
        from apps.tenancy.feature_registry import TENANT_REGISTRY

        items: list[dict] = []
        seen: set[str] = set()
        for group in TENANT_REGISTRY:
            group_label = group.get("group", "")
            for it in group.get("children", []):
                key = it["key"]
                if key in seen:
                    continue
                seen.add(key)
                items.append({
                    "key": key,
                    "name": it["name"],
                    "group": group_label,
                    "parent_key": None,
                    "description": "",
                })
        return Response(items)
