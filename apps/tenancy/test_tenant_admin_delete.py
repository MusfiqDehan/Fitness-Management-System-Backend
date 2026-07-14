"""Tenant Django-admin delete: force-drop schema + protect public tenant.

Uses TransactionTestCase because force_drop issues DROP SCHEMA CASCADE, which
cannot run inside TestCase's per-test atomic block (pending trigger events).
"""

from unittest.mock import MagicMock

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.db import connection
from django.test import RequestFactory, TestCase, TransactionTestCase
from django_tenants.utils import get_public_schema_name, schema_context

from apps.identity.models import User
from apps.tenancy.admin import TenantAdmin
from apps.tenancy.models import Domain, Tenant


def _attach_messages(request):
    setattr(request, "session", "session")
    setattr(request, "_messages", FallbackStorage(request))
    return request


def _ensure_public_tenant():
    public_name = get_public_schema_name()
    with schema_context("public"):
        public, _ = Tenant.objects.get_or_create(
            schema_name=public_name,
            defaults={
                "name": "Public",
                "slug": "public-admin-del",
                "code": "PUBLICADM",
                "status": "active",
                "is_trial": False,
            },
        )
        return public


def _force_cleanup(schema_name: str):
    connection.set_schema_to_public()
    with schema_context("public"):
        tenant = Tenant.objects.filter(schema_name=schema_name).first()
        if tenant is not None:
            try:
                tenant.delete(force_drop=True)
            except Exception:
                pass
        with connection.cursor() as cur:
            cur.execute('DROP SCHEMA IF EXISTS "%s" CASCADE' % schema_name)


def _create_tenant_with_user(schema_name: str, code: str):
    _force_cleanup(schema_name)
    with schema_context("public"):
        tenant = Tenant.objects.create(
            schema_name=schema_name,
            name=f"Tenant {code}",
            slug=schema_name.replace("_", "-"),
            code=code,
            owner_email=f"owner@{schema_name}.test",
            billing_email=f"owner@{schema_name}.test",
            status="trial",
            is_trial=True,
        )
        Domain.objects.create(
            domain=f"{schema_name}.localhost",
            tenant=tenant,
            is_primary=True,
        )
    with schema_context(schema_name):
        User.objects.create_user(
            email=f"member@{schema_name}.test",
            password="Test@1234",
            tenant=tenant,
        )
    return tenant


class TenantAdminDeletePermissionTests(TestCase):
    def setUp(self):
        self.admin = TenantAdmin(Tenant, AdminSite())
        self.factory = RequestFactory()
        _ensure_public_tenant()
        with schema_context("public"):
            self.staff = get_user_model().objects.create_superuser(
                email="root-admin-del-perm@test.local",
                password="Test@1234",
            )

    def test_has_delete_permission_false_for_public(self):
        public = _ensure_public_tenant()
        request = self.factory.get("/admin/tenancy/tenant/")
        request.user = self.staff
        self.assertFalse(self.admin.has_delete_permission(request, public))

    def test_delete_model_calls_force_drop(self):
        request = _attach_messages(self.factory.post("/admin/tenancy/tenant/"))
        request.user = self.staff
        tenant = MagicMock(spec=Tenant)
        tenant.schema_name = "dummy_tenant"
        self.admin.delete_model(request, tenant)
        tenant.delete.assert_called_once_with(force_drop=True)

    def test_delete_model_skips_public_without_calling_delete(self):
        request = _attach_messages(self.factory.post("/admin/tenancy/tenant/"))
        request.user = self.staff
        tenant = MagicMock(spec=Tenant)
        tenant.schema_name = get_public_schema_name()
        self.admin.delete_model(request, tenant)
        tenant.delete.assert_not_called()


class TenantAdminDeleteIntegrationTests(TransactionTestCase):
    def setUp(self):
        self.admin = TenantAdmin(Tenant, AdminSite())
        self.factory = RequestFactory()
        _ensure_public_tenant()
        with schema_context("public"):
            self.staff = get_user_model().objects.create_superuser(
                email="root-admin-del-int@test.local",
                password="Test@1234",
            )

    def _request(self):
        request = self.factory.post("/admin/tenancy/tenant/")
        request.user = self.staff
        return _attach_messages(request)

    def test_admin_delete_model_drops_schema_despite_cross_schema_user_fk(self):
        schema_name = "tenant_admin_del_one"
        try:
            tenant = _create_tenant_with_user(schema_name, "ADMINDEL1")
            with schema_context("public"):
                self.admin.delete_model(self._request(), tenant)
                self.assertFalse(
                    Tenant.objects.filter(schema_name=schema_name).exists()
                )
                with connection.cursor() as cur:
                    cur.execute(
                        "SELECT 1 FROM information_schema.schemata WHERE schema_name=%s",
                        [schema_name],
                    )
                    self.assertIsNone(cur.fetchone())
        finally:
            _force_cleanup(schema_name)

    def test_admin_delete_queryset_skips_public_and_drops_others(self):
        schema_a = "tenant_admin_del_a"
        schema_b = "tenant_admin_del_b"
        try:
            tenant_a = _create_tenant_with_user(schema_a, "ADMINDELA")
            tenant_b = _create_tenant_with_user(schema_b, "ADMINDELB")
            public = _ensure_public_tenant()
            with schema_context("public"):
                qs = Tenant.objects.filter(pk__in=[public.pk, tenant_a.pk, tenant_b.pk])
                self.admin.delete_queryset(self._request(), qs)
                self.assertTrue(
                    Tenant.objects.filter(schema_name=get_public_schema_name()).exists()
                )
                self.assertFalse(Tenant.objects.filter(schema_name=schema_a).exists())
                self.assertFalse(Tenant.objects.filter(schema_name=schema_b).exists())
                with connection.cursor() as cur:
                    cur.execute(
                        "SELECT schema_name FROM information_schema.schemata "
                        "WHERE schema_name = ANY(%s)",
                        [[schema_a, schema_b]],
                    )
                    self.assertEqual(cur.fetchall(), [])
        finally:
            _force_cleanup(schema_a)
            _force_cleanup(schema_b)

    def test_model_delete_rejects_public_tenant(self):
        public = _ensure_public_tenant()
        with schema_context("public"):
            with self.assertRaises(PermissionError):
                public.delete(force_drop=True)
            self.assertTrue(
                Tenant.objects.filter(schema_name=get_public_schema_name()).exists()
            )
