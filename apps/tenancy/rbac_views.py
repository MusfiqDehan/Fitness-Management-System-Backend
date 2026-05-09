"""API views for RBAC, packages, and tenant feature flags (Phases 0+1).

Kept separate from the existing `views.py` to avoid bloat. All views
here run on the public schema; tenant-scoped RBAC views live in
`apps.access.views`.
"""
from django.db import transaction
from django.utils import timezone
from django_tenants.utils import get_public_schema_name, schema_context
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.models import User
from .constants import PLATFORM_MODULES, PLATFORM_MODULE_KEYS
from .models import (
    Feature,
    Invitation,
    PlatformPackage,
    PlatformPackageFeature,
    PlatformRole,
    PlatformRolePermission,
    PlatformUserRole,
    Tenant,
    TenantFeatureFlag,
)
from .permissions import (
    IsPlatformFeaturePermission,
    IsPlatformSuperAdmin,
    get_platform_user_permission_level,
    is_superadmin,
)
from .rbac_serializers import (
    FeatureSerializer,
    PlatformPackageFeatureBulkSerializer,
    PlatformPackageSerializer,
    PlatformRolePermissionsBulkSerializer,
    PlatformRoleSerializer,
    PlatformUserRoleSerializer,
    PublicPlatformPackageSerializer,
    TenantFeatureFlagBulkUpdateSerializer,
    TenantFeatureFlagSerializer,
)
from .serializers import (
    PlatformInvitationCreateSerializer,
    PlatformInvitationListSerializer,
    PlatformInviteAcceptSerializer,
)
from .services import sync_tenant_features


# ===============================================================
# Platform Modules registry (read-only)
# ===============================================================
class PlatformModuleListView(APIView):
    """Returns the hardcoded list of platform modules. For UI dropdowns.

    Available to anyone who can manage platform users (i.e. role editors),
    so non-superuser admins can populate the permission matrix UI.
    """

    permission_classes = [
        IsPlatformFeaturePermission.require("platform.platform_users", "view"),
    ]

    def get(self, request):
        # Source from the canonical registry so the platform-team permission
        # matrix follows the same single source of truth as the sidebar.
        #
        # Only modules that have a `route` are returned: a module without a
        # frontend page can't meaningfully be granted to a role yet. To expose
        # a new module here, simply add its `route` in
        # `apps/tenancy/feature_registry.py` and ship the page — no edits to
        # this view are required.
        #
        # `?include_unshipped=1` opts in to all gateable modules (used by the
        # backend itself / advanced tooling).
        from .feature_registry import PLATFORM_REGISTRY

        include_unshipped = request.query_params.get("include_unshipped") == "1"

        items: list[dict] = []
        seen: set[str] = set()
        for group in PLATFORM_REGISTRY:
            group_label = group.get("group", "")
            for it in group.get("children", []):
                key = it["key"]
                if key in seen:
                    continue
                if not include_unshipped and not it.get("route"):
                    continue
                seen.add(key)
                items.append({"key": key, "name": it["name"], "group": group_label})

        if include_unshipped:
            for k, v in PLATFORM_MODULES.items():
                if k not in seen:
                    items.append({"key": k, "name": v, "group": ""})
        return Response(items)


# ===============================================================
# Platform Roles
# ===============================================================
class PlatformRoleListCreateView(generics.ListCreateAPIView):
    queryset = PlatformRole.objects.all().prefetch_related("permissions", "user_assignments")
    serializer_class = PlatformRoleSerializer
    permission_classes = [
        IsPlatformFeaturePermission.require("platform.platform_users", "view"),
    ]

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsPlatformFeaturePermission.require("platform.platform_users", "edit")()]
        return super().get_permissions()


class PlatformRoleDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = PlatformRole.objects.all().prefetch_related("permissions")
    serializer_class = PlatformRoleSerializer
    permission_classes = [
        IsPlatformFeaturePermission.require("platform.platform_users", "edit"),
    ]

    def perform_destroy(self, instance):
        if instance.is_system:
            from rest_framework.exceptions import ValidationError
            raise ValidationError("System roles cannot be deleted.")
        instance.delete()


class PlatformRolePermissionsView(APIView):
    """GET / PUT permissions for a specific platform role."""

    permission_classes = [
        IsPlatformFeaturePermission.require("platform.platform_users", "edit"),
    ]

    def get(self, request, role_id):
        role = generics.get_object_or_404(PlatformRole, pk=role_id)
        perms = role.permissions.all()
        return Response({
            "role_id": role.id,
            "permissions": [
                {"module_key": p.module_key, "permission_level": p.permission_level}
                for p in perms
            ],
        })

    def put(self, request, role_id):
        role = generics.get_object_or_404(PlatformRole, pk=role_id)
        serializer = PlatformRolePermissionsBulkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            existing = {p.module_key: p for p in role.permissions.all()}
            for entry in serializer.validated_data["permissions"]:
                key = entry["module_key"]
                level = entry["permission_level"]
                if key in existing:
                    p = existing[key]
                    if p.permission_level != level:
                        p.permission_level = level
                        p.save(update_fields=["permission_level"])
                else:
                    PlatformRolePermission.objects.create(
                        role=role, module_key=key, permission_level=level
                    )
        return Response({"status": "ok"})


# ===============================================================
# Platform User-Role assignments
# ===============================================================
class PlatformUserRoleListCreateView(generics.ListCreateAPIView):
    queryset = PlatformUserRole.objects.select_related("user", "role").all()
    serializer_class = PlatformUserRoleSerializer
    permission_classes = [
        IsPlatformFeaturePermission.require("platform.platform_users", "view"),
    ]

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsPlatformFeaturePermission.require("platform.platform_users", "edit")()]
        return super().get_permissions()

    def perform_create(self, serializer):
        serializer.save(assigned_by=self.request.user)


class PlatformUserRoleDetailView(generics.RetrieveDestroyAPIView):
    queryset = PlatformUserRole.objects.all()
    serializer_class = PlatformUserRoleSerializer
    permission_classes = [
        IsPlatformFeaturePermission.require("platform.platform_users", "edit"),
    ]


# ===============================================================
# Feature Registry (superadmin only)
# ===============================================================
class FeatureListCreateView(generics.ListCreateAPIView):
    queryset = Feature.objects.all()
    serializer_class = FeatureSerializer
    permission_classes = [
        IsPlatformFeaturePermission.require("platform.features", "view"),
    ]

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsPlatformFeaturePermission.require("platform.features", "edit")()]
        return super().get_permissions()


class FeatureDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Feature.objects.all()
    serializer_class = FeatureSerializer
    permission_classes = [
        IsPlatformFeaturePermission.require("platform.features", "edit"),
    ]

    def perform_destroy(self, instance):
        if instance.is_system:
            from rest_framework.exceptions import ValidationError
            raise ValidationError("System features cannot be deleted.")
        instance.delete()


# ===============================================================
# Platform Packages
# ===============================================================
class PublicPlatformPackageListView(generics.ListAPIView):
    """Public endpoint: lists packages for the landing page pricing section."""

    queryset = PlatformPackage.objects.filter(is_active=True, is_public=True)
    serializer_class = PublicPlatformPackageSerializer
    permission_classes = [AllowAny]


class PlatformPackageListCreateView(generics.ListCreateAPIView):
    queryset = PlatformPackage.objects.all().prefetch_related("package_features__feature")
    serializer_class = PlatformPackageSerializer
    permission_classes = [
        IsPlatformFeaturePermission.require("platform.packages", "view"),
    ]

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsPlatformFeaturePermission.require("platform.packages", "edit")()]
        return super().get_permissions()


class PlatformPackageDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = PlatformPackage.objects.all().prefetch_related("package_features__feature")
    serializer_class = PlatformPackageSerializer
    permission_classes = [
        IsPlatformFeaturePermission.require("platform.packages", "edit"),
    ]


class PlatformPackageFeaturesView(APIView):
    """GET / PUT the feature mapping for a package."""

    permission_classes = [
        IsPlatformFeaturePermission.require("platform.packages", "edit"),
    ]

    def get(self, request, package_id):
        package = generics.get_object_or_404(PlatformPackage, pk=package_id)
        return Response({
            "package_id": package.id,
            "feature_ids": list(
                package.package_features.filter(is_enabled=True).values_list("feature_id", flat=True)
            ),
        })

    def put(self, request, package_id):
        package = generics.get_object_or_404(PlatformPackage, pk=package_id)
        serializer = PlatformPackageFeatureBulkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        feature_ids = set(serializer.validated_data["feature_ids"])
        with transaction.atomic():
            existing = {
                pf.feature_id: pf
                for pf in package.package_features.all()
            }
            # Add new
            for fid in feature_ids:
                if fid not in existing:
                    PlatformPackageFeature.objects.create(
                        package=package, feature_id=fid, is_enabled=True
                    )
                elif not existing[fid].is_enabled:
                    existing[fid].is_enabled = True
                    existing[fid].save(update_fields=["is_enabled"])
            # Disable removed
            for fid, pf in existing.items():
                if fid not in feature_ids and pf.is_enabled:
                    pf.is_enabled = False
                    pf.save(update_fields=["is_enabled"])
        return Response({"status": "ok"})


# ===============================================================
# Tenant Feature Flags (per-tenant superadmin overrides)
# ===============================================================
class TenantFeatureFlagListView(APIView):
    """GET / PUT a tenant's feature flags (superadmin override management)."""

    permission_classes = [
        IsPlatformFeaturePermission.require("platform.tenants", "view"),
    ]

    def get(self, request, tenant_id):
        tenant = generics.get_object_or_404(Tenant, pk=tenant_id)
        flags = TenantFeatureFlag.objects.filter(tenant=tenant).select_related("feature")
        return Response(TenantFeatureFlagSerializer(flags, many=True).data)

    def put(self, request, tenant_id):
        # Edit-level required for write
        edit_perm = IsPlatformFeaturePermission.require(
            "platform.tenants", "edit"
        )()
        if not edit_perm.has_permission(request, self):
            return Response({"detail": "Insufficient permissions."}, status=status.HTTP_403_FORBIDDEN)

        tenant = generics.get_object_or_404(Tenant, pk=tenant_id)
        serializer = TenantFeatureFlagBulkUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        actor_email = getattr(request.user, "email", "") or ""
        with transaction.atomic():
            for override in serializer.validated_data["overrides"]:
                feature = Feature.objects.filter(key=override["feature_key"]).first()
                if not feature:
                    continue
                TenantFeatureFlag.objects.update_or_create(
                    tenant=tenant,
                    feature=feature,
                    defaults={
                        "is_enabled": bool(override["is_enabled"]),
                        "source": TenantFeatureFlag.SOURCE_OVERRIDE,
                        "grace_until": None,
                        "updated_by_email": actor_email,
                    },
                )
        return Response({"status": "ok"})


class TenantFeatureFlagResyncView(APIView):
    """POST: re-sync flags from package (clears overrides if force=true)."""

    permission_classes = [
        IsPlatformFeaturePermission.require("platform.tenants", "edit"),
    ]

    def post(self, request, tenant_id):
        tenant = generics.get_object_or_404(Tenant, pk=tenant_id)
        force_revoke = bool(request.data.get("force_revoke"))
        summary = sync_tenant_features(tenant, force_revoke=force_revoke)
        return Response(summary)


# ===============================================================
# Current tenant: enabled features (used by frontend)
# ===============================================================
class CurrentTenantFeatureListView(APIView):
    """Authenticated view: returns enabled features for the current tenant."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        tenant = getattr(request.user, "tenant", None)
        if tenant is None:
            return Response({"feature_keys": []})
        flags = TenantFeatureFlag.objects.filter(tenant=tenant).select_related("feature")
        keys = [f.feature.key for f in flags if f.is_effectively_enabled]
        return Response({"tenant_id": tenant.id, "feature_keys": keys})


# ===============================================================
# Platform Team Invitations (email-based)
# ===============================================================
class PlatformInvitationListCreateView(APIView):
    """Superadmin-only: list pending platform team invites and issue new ones."""

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsPlatformFeaturePermission.require("platform.platform_users", "edit")()]
        return [IsPlatformFeaturePermission.require("platform.platform_users", "view")()]

    def get(self, request):
        invitations = (
            Invitation.objects
            .filter(token_type=Invitation.TOKEN_TYPE_PLATFORM_INVITE)
            .select_related("platform_role")
            .order_by("-created_at")
        )
        return Response(
            PlatformInvitationListSerializer(invitations, many=True).data
        )

    def post(self, request):
        serializer = PlatformInvitationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data
        # Lazy imports to avoid a circular dependency with views.py
        from .views import _build_frontend_url, _issue_email, _record_audit
        from urllib.parse import quote

        with transaction.atomic():
            raw_token, invitation = Invitation.issue_token(
                token_type=Invitation.TOKEN_TYPE_PLATFORM_INVITE,
                email=payload["email"],
                invitee_full_name=payload.get("full_name", ""),
                subdomain="",  # not relevant for platform invites
                company_name="Platform Team",
                invited_by_email=getattr(request.user, "email", "") or "",
                ttl_minutes=60 * 48,  # 2 days
                metadata={"role_slug": payload["role"].slug, "role_name": payload["role"].name},
                platform_role=payload["role"],
            )

            accept_url = _build_frontend_url(
                f"/accept-platform-invite?token={quote(raw_token)}",
                prefer_public=True,
            )

            _issue_email(
                tenant=None,
                to_email=payload["email"],
                purpose="invitation",
                subject="You've been invited to the Platform Team",
                template_name="tenancy/emails/platform_invitation_email.html",
                context={
                    "full_name": payload.get("full_name", "") or payload["email"],
                    "role_name": payload["role"].name,
                    "invitation_url": accept_url,
                    "expires_at": invitation.expires_at,
                    "invited_by": getattr(request.user, "email", "") or "Superadmin",
                },
                fallback_text=(
                    f"You've been invited to join the Platform Team as "
                    f"{payload['role'].name}. Accept by visiting: {accept_url}"
                ),
            )

            _record_audit(
                request,
                action="platform.invitation.issued",
                target_type="platform_invitation",
                target_id=invitation.id,
                metadata={"email": payload["email"], "role": payload["role"].slug},
            )

        return Response(
            {
                "message": "Invitation sent.",
                "invitation_id": invitation.id,
                "expires_at": invitation.expires_at,
            },
            status=status.HTTP_201_CREATED,
        )


class PlatformInvitationRevokeView(APIView):
    """Superadmin-only: revoke a pending platform invitation."""

    permission_classes = [
        IsPlatformFeaturePermission.require("platform.platform_users", "edit"),
    ]

    def delete(self, request, pk):
        invitation = generics.get_object_or_404(
            Invitation,
            pk=pk,
            token_type=Invitation.TOKEN_TYPE_PLATFORM_INVITE,
        )
        if invitation.used_at is not None:
            return Response(
                {"detail": "Invitation has already been accepted."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        invitation.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PlatformInviteValidateView(APIView):
    """Public: validate a platform-invite token. Returns email + role for the accept page."""

    permission_classes = [AllowAny]

    def get(self, request):
        token = request.query_params.get("token", "")
        invitation = Invitation.from_raw_token(token)
        if invitation is None or invitation.token_type != Invitation.TOKEN_TYPE_PLATFORM_INVITE:
            return Response({"detail": "Invalid token."}, status=status.HTTP_400_BAD_REQUEST)
        if invitation.used_at is not None:
            return Response({"detail": "This invitation has already been used."}, status=status.HTTP_400_BAD_REQUEST)
        if invitation.is_expired:
            return Response({"detail": "This invitation has expired."}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            "email": invitation.email,
            "full_name": invitation.invitee_full_name,
            "role_name": invitation.platform_role.name if invitation.platform_role_id else "",
            "role_slug": invitation.platform_role.slug if invitation.platform_role_id else "",
            "invited_by": invitation.invited_by_email,
            "expires_at": invitation.expires_at,
        })


class PlatformInviteAcceptView(APIView):
    """Public: accept a platform-invite token; creates/updates a public-schema User
    and assigns the platform role.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PlatformInviteAcceptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        with transaction.atomic():
            invitation = Invitation.from_raw_token(payload["token"], for_update=True)
            if invitation is None or invitation.token_type != Invitation.TOKEN_TYPE_PLATFORM_INVITE:
                return Response({"detail": "Invalid token."}, status=status.HTTP_400_BAD_REQUEST)
            if invitation.used_at is not None:
                return Response({"detail": "This invitation has already been used."}, status=status.HTTP_400_BAD_REQUEST)
            if invitation.is_expired:
                return Response({"detail": "This invitation has expired."}, status=status.HTTP_400_BAD_REQUEST)
            if invitation.platform_role_id is None:
                return Response({"detail": "Invitation is missing a role."}, status=status.HTTP_400_BAD_REQUEST)

            email = invitation.email.lower().strip()
            full_name = (payload.get("full_name") or invitation.invitee_full_name or "").strip()
            now = timezone.now()

            with schema_context(get_public_schema_name()):
                user = User.objects.filter(email__iexact=email).first()
                if user is None:
                    user = User.objects.create_user(
                        email=email,
                        password=payload["password"],
                        role="staff",
                        full_name=full_name,
                        tenant=None,
                        is_staff=True,
                        is_superuser=False,
                        email_verified=True,
                        password_set_at=now,
                    )
                else:
                    if user.tenant_id is not None:
                        return Response(
                            {"detail": "An account with this email belongs to a tenant and cannot be added to the platform team."},
                            status=status.HTTP_400_BAD_REQUEST,
                        )
                    user.set_password(payload["password"])
                    user.is_active = True
                    user.is_staff = True
                    user.email_verified = True
                    user.password_set_at = now
                    if full_name and not user.full_name:
                        user.full_name = full_name
                    user.save()

                PlatformUserRole.objects.get_or_create(
                    user=user,
                    role=invitation.platform_role,
                )

            invitation.used_at = now
            invitation.save(update_fields=["used_at"])

        return Response({
            "message": "Welcome to the platform team. You can now sign in.",
            "email": email,
        })


# ===============================================================
# Current user's effective platform permissions
# ===============================================================
class MyPlatformPermissionsView(APIView):
    """Returns the calling user's effective platform module permissions.

    Used by the frontend to filter the Platform Admin sidebar and to gate
    client-side routes. The backend remains authoritative; this endpoint
    just lets the UI avoid advertising features the user cannot use.

    Response shape:
        {
          "is_superuser": bool,
          "is_platform_user": bool,         # user.tenant is None
          "roles": [{"id", "slug", "name"}],
          "permissions": {<module_key>: "none"|"view"|"edit"|"full"},
          "modules": [{"key", "name"}, ...]
        }

    For tenant-scoped users this returns is_platform_user=False and
    empty roles/permissions (no error), so the same client can call it
    on either domain without branching.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        is_super = is_superadmin(user)
        is_platform_user = is_super or getattr(user, "tenant_id", None) is None

        roles_data = []
        permissions = {key: "none" for key in PLATFORM_MODULES}

        if is_super:
            for key in PLATFORM_MODULES:
                permissions[key] = "full"
        elif is_platform_user:
            assignments = (
                PlatformUserRole.objects
                .filter(user=user)
                .select_related("role")
            )
            roles_data = [
                {"id": a.role_id, "slug": a.role.slug, "name": a.role.name}
                for a in assignments
            ]
            for key in PLATFORM_MODULES:
                permissions[key] = get_platform_user_permission_level(user, key)

        return Response({
            "is_superuser": is_super,
            "is_platform_user": is_platform_user,
            "roles": roles_data,
            "permissions": permissions,
            "modules": [{"key": k, "name": v} for k, v in PLATFORM_MODULES.items()],
        })


# ===============================================================
# Feature Registry — single source of truth for sidebar items.
# ===============================================================
class FeatureRegistryView(APIView):
    """Returns the canonical PLATFORM/TENANT/SHARED feature registry.

    Auth-required only — the frontend uses this purely to render labels and
    routes. The actual access decision is still made by `hasPlatformPermission`
    / `hasFeature` against the user's permissions, and the backend enforces
    every endpoint regardless.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .feature_registry import build_api_payload
        return Response(build_api_payload())
