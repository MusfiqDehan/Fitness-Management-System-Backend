from django.test import TestCase
from django_tenants.utils import schema_context

from apps.crm.email_delivery import resolve_operational_mail_route, resolve_platform_mail_route
from apps.crm.models import EmailConfig, TenantEmailConfig
from apps.tenancy.models import Tenant


class TenantEmailConfigIsolationTests(TestCase):
    def setUp(self):
        with schema_context("public"):
            self.tenant_a = Tenant.objects.create(
                schema_name="tenant_email_a",
                name="Tenant A",
                slug="tenant-a",
                code="TEMAILA",
                owner_email="owner-a@test.local",
                billing_email="owner-a@test.local",
                status="active",
                is_trial=False,
            )
            self.tenant_b = Tenant.objects.create(
                schema_name="tenant_email_b",
                name="Tenant B",
                slug="tenant-b",
                code="TEMAILB",
                owner_email="owner-b@test.local",
                billing_email="owner-b@test.local",
                status="active",
                is_trial=False,
            )
            self.config_a = TenantEmailConfig.objects.create(
                tenant=self.tenant_a,
                name="Tenant A Gmail",
                host_user="tenant-a@gmail.com",
                default_from_email="tenant-a@gmail.com",
                is_active=True,
            )
            self.config_b = TenantEmailConfig.objects.create(
                tenant=self.tenant_b,
                name="Tenant B Gmail",
                host_user="tenant-b@gmail.com",
                default_from_email="tenant-b@gmail.com",
                is_active=True,
            )

    def test_operational_route_uses_matching_tenant_config(self):
        from_a, _ = resolve_operational_mail_route(self.tenant_a)
        from_b, _ = resolve_operational_mail_route(self.tenant_b)

        self.assertEqual(from_a, "tenant-a@gmail.com")
        self.assertEqual(from_b, "tenant-b@gmail.com")

    def test_operational_route_falls_back_to_platform_config(self):
        with schema_context("public"):
            EmailConfig.objects.create(
                name="Platform Gmail",
                host_user="platform@gmail.com",
                default_from_email="platform@gmail.com",
                is_active=True,
            )
            TenantEmailConfig.objects.filter(tenant=self.tenant_a).delete()

        from_email, _ = resolve_operational_mail_route(self.tenant_a)
        self.assertEqual(from_email, "platform@gmail.com")

    def test_platform_route_ignores_tenant_configs(self):
        with schema_context("public"):
            EmailConfig.objects.create(
                name="Platform Gmail",
                host_user="platform@gmail.com",
                default_from_email="platform@gmail.com",
                is_active=True,
            )

        from_email, _, _ = resolve_platform_mail_route()
        self.assertEqual(from_email, "platform@gmail.com")
