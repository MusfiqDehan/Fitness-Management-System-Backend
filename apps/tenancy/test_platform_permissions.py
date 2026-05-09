"""Tests for the platform-permission endpoint and feature-gated views.

Covers the security goal: invited platform users must only see/touch the
modules their PlatformRole grants. The backend stays the source of truth.
"""
from django.test import override_settings
from django.urls import URLPattern, URLResolver, get_resolver
from django_tenants.utils import schema_context
from rest_framework import status
from rest_framework.test import APITestCase

from apps.identity.models import User
from apps.tenancy.constants import PLATFORM_MODULES
from apps.tenancy.models import (
    Domain,
    PlatformRole,
    PlatformRolePermission,
    PlatformUserRole,
    Tenant,
)


@override_settings(PUBLIC_DOMAIN="testserver")
class PlatformPermissionsApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        with schema_context("public"):
            cls.public, _ = Tenant.objects.get_or_create(
                schema_name="public",
                defaults=dict(
                    name="Public",
                    slug="public",
                    code="PLATPERMTEST",
                    owner_email="root@perm.test",
                    billing_email="root@perm.test",
                    status="active",
                    is_trial=False,
                ),
            )
            Domain.objects.get_or_create(
                domain="testserver",
                tenant=cls.public,
                defaults={"is_primary": True},
            )
            cls.superuser = User.objects.create_superuser(
                email="root@perm.test",
                password="Test@1234",
                tenant=cls.public,
            )
            cls.staff = User.objects.create_user(
                email="staff@perm.test",
                password="Test@1234",
                tenant=cls.public,
            )
            cls.staff.is_staff = True
            cls.staff.save(update_fields=["is_staff"])

            cls.role = PlatformRole.objects.create(
                name="Team Viewer",
                slug="team-viewer",
            )
            PlatformRolePermission.objects.create(
                role=cls.role,
                module_key="platform.platform_users",
                permission_level="view",
            )
            PlatformUserRole.objects.create(user=cls.staff, role=cls.role)

            cls.tenant = Tenant.objects.create(
                schema_name="tenant_perm_test",
                name="Tenant Perm",
                slug="tenant-perm",
                code="TENANTPERM",
                owner_email="ten@perm.test",
                billing_email="ten@perm.test",
                status="active",
                is_trial=False,
            )
            Domain.objects.create(
                domain="tenantperm.testserver",
                tenant=cls.tenant,
                is_primary=True,
            )

        with schema_context(cls.tenant.schema_name):
            cls.tenant_user = User.objects.create_user(
                email="member@perm.test",
                password="Test@1234",
                tenant=cls.tenant,
            )

    # ── /me/platform-permissions/ ────────────────────────────────────────

    def test_superuser_gets_full_on_every_module(self):
        self.client.force_authenticate(user=self.superuser)
        res = self.client.get(
            "/api/v1/tenants/admin/me/platform-permissions/",
            HTTP_HOST="testserver",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["is_superuser"])
        self.assertTrue(res.data["is_platform_user"])
        for key in PLATFORM_MODULES:
            self.assertEqual(res.data["permissions"][key], "full")

    def test_custom_role_user_gets_only_assigned_module(self):
        self.client.force_authenticate(user=self.staff)
        res = self.client.get(
            "/api/v1/tenants/admin/me/platform-permissions/",
            HTTP_HOST="testserver",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertFalse(res.data["is_superuser"])
        self.assertTrue(res.data["is_platform_user"])
        perms = res.data["permissions"]
        self.assertEqual(perms["platform.platform_users"], "view")
        self.assertEqual(perms["platform.tenants"], "none")
        self.assertEqual(perms["platform.billing"], "none")
        slugs = {r["slug"] for r in res.data["roles"]}
        self.assertIn("team-viewer", slugs)

    def test_tenant_user_gets_empty_payload(self):
        self.client.force_authenticate(user=self.tenant_user)
        res = self.client.get(
            "/api/v1/tenants/admin/me/platform-permissions/",
            HTTP_HOST="testserver",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertFalse(res.data["is_superuser"])
        self.assertFalse(res.data["is_platform_user"])
        for level in res.data["permissions"].values():
            self.assertEqual(level, "none")

    # ── Feature-gating enforcement on tenant admin endpoints ─────────────

    def test_custom_role_without_tenants_perm_cannot_list_tenants(self):
        self.client.force_authenticate(user=self.staff)
        res = self.client.get(
            "/api/v1/tenants/admin/tenants/",
            HTTP_HOST="testserver",
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_custom_role_with_view_only_cannot_create_platform_role(self):
        self.client.force_authenticate(user=self.staff)
        list_res = self.client.get(
            "/api/v1/tenants/admin/platform-roles/",
            HTTP_HOST="testserver",
        )
        self.assertEqual(list_res.status_code, status.HTTP_200_OK)
        create_res = self.client.post(
            "/api/v1/tenants/admin/platform-roles/",
            {"name": "Hacker", "slug": "hacker"},
            format="json",
            HTTP_HOST="testserver",
        )
        self.assertEqual(create_res.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_request_is_rejected(self):
        res = self.client.get(
            "/api/v1/tenants/admin/tenants/",
            HTTP_HOST="testserver",
        )
        self.assertIn(
            res.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )


class PlatformUrlPermissionAuditTests(APITestCase):
    """Introspection: every tenancy admin URL must require authentication."""

    def _walk(self, patterns, prefix=""):
        for entry in patterns:
            if isinstance(entry, URLResolver):
                yield from self._walk(entry.url_patterns, prefix + str(entry.pattern))
            elif isinstance(entry, URLPattern):
                yield prefix + str(entry.pattern), entry

    def test_no_admin_endpoint_is_publicly_accessible(self):
        offenders: list[str] = []
        for path, pattern in self._walk(get_resolver().url_patterns):
            if "tenants/admin/" not in path:
                continue
            view = pattern.callback
            view_cls = getattr(view, "view_class", None) or getattr(view, "cls", None)
            if view_cls is None:
                continue
            perms = getattr(view_cls, "permission_classes", ())
            names = {p.__name__ for p in perms}
            ok = (
                "IsAuthenticated" in names
                or any(n.startswith("IsPlatformFeaturePermission") for n in names)
                or "IsPlatformSuperAdmin" in names
            )
            if not ok:
                offenders.append(f"{path} -> {view_cls.__name__} ({sorted(names)})")
        self.assertEqual(
            offenders, [], "Unprotected admin endpoints found:\n" + "\n".join(offenders)
        )
