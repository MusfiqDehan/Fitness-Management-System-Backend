"""Platform Admin overview dashboard endpoint."""
from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from django_tenants.utils import schema_context
from rest_framework import status
from rest_framework.test import APITestCase

from apps.identity.models import User
from apps.tenancy.models import (
    Domain,
    PlatformPackage,
    PlatformRole,
    PlatformRolePermission,
    PlatformUserRole,
    Tenant,
    TenantSubscriptionInvoice,
)

OVERVIEW_URL = "/api/v1/tenants/admin/platform-overview/"


@override_settings(PUBLIC_DOMAIN="testserver")
class PlatformOverviewApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        with schema_context("public"):
            cls.public, _ = Tenant.objects.get_or_create(
                schema_name="public",
                defaults=dict(
                    name="Public",
                    slug="public",
                    code="OVERVIEW",
                    owner_email="root@overview.test",
                    billing_email="root@overview.test",
                    status="active",
                    is_trial=False,
                ),
            )
            Domain.objects.get_or_create(
                domain="testserver",
                tenant=cls.public,
                defaults={"is_primary": True},
            )

            cls.superadmin = User.objects.create_user(
                email="root@overview.test",
                password="Test@1234",
                tenant=cls.public,
            )
            cls.superadmin.is_superuser = True
            cls.superadmin.is_staff = True
            cls.superadmin.save(update_fields=["is_superuser", "is_staff"])

            # A platform user with no overview permission, to prove gating.
            cls.outsider = User.objects.create_user(
                email="outsider@overview.test",
                password="Test@1234",
                tenant=cls.public,
            )
            role = PlatformRole.objects.create(name="Blogs Only", slug="blogs-only-overview")
            PlatformRolePermission.objects.create(
                role=role, module_key="platform.cms.blogs", permission_level="view"
            )
            PlatformUserRole.objects.create(user=cls.outsider, role=role)

            PlatformPackage.objects.update_or_create(
                slug="pro",
                defaults={"name": "Pro", "price_monthly": Decimal("50.00")},
            )

            now = timezone.now()
            cls.paying = Tenant.objects.create(
                schema_name="ov_paying",
                name="Paying Gym",
                slug="ov-paying",
                code="OVPAY",
                owner_email="a@pay.test",
                billing_email="a@pay.test",
                plan="pro",
                status="active",
                is_enabled=True,
                is_trial=False,
            )
            cls.trialing = Tenant.objects.create(
                schema_name="ov_trial",
                name="Trial Gym",
                slug="ov-trial",
                code="OVTRI",
                owner_email="b@trial.test",
                billing_email="b@trial.test",
                plan="pro",
                status="trial",
                is_enabled=True,
                is_trial=True,
                trial_ends_at=now + timedelta(days=5),
            )

            TenantSubscriptionInvoice.objects.create(
                tenant=cls.paying,
                package_slug="pro",
                package_name="Pro",
                amount=Decimal("50.00"),
                currency="USD",
                tran_id="ov-tran-1",
                status=TenantSubscriptionInvoice.STATUS_SUCCESS,
            )

    def setUp(self):
        cache.clear()

    def _get(self, user):
        self.client.force_authenticate(user=user)
        return self.client.get(OVERVIEW_URL, HTTP_HOST="testserver")

    def test_superadmin_gets_the_full_payload(self):
        res = self._get(self.superadmin)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        for section in (
            "tenants",
            "accounts",
            "revenue",
            "plan_distribution",
            "recent_tenants",
            "recent_invoices",
            "expiring_trials",
        ):
            self.assertIn(section, res.data)

    def test_tenant_counters_exclude_the_public_schema(self):
        res = self._get(self.superadmin)
        tenants = res.data["tenants"]

        # Two real tenants; the public row must not be counted as a customer.
        self.assertEqual(tenants["total"], 2)
        self.assertEqual(tenants["active"], 2)
        self.assertEqual(tenants["trial"], 1)

    def test_mrr_counts_billable_tenants_and_skips_trials(self):
        res = self._get(self.superadmin)

        # Only the non-trial tenant on the $50 Pro plan contributes.
        self.assertEqual(Decimal(res.data["revenue"]["mrr"]), Decimal("50.00"))

    def test_revenue_sums_successful_invoices_in_the_dominant_currency(self):
        res = self._get(self.superadmin)
        revenue = res.data["revenue"]

        self.assertEqual(revenue["currency"], "USD")
        self.assertEqual(Decimal(revenue["collected_this_month"]), Decimal("50.00"))
        self.assertEqual(len(revenue["series"]), 6)

    def test_expiring_trials_are_surfaced_with_days_left(self):
        res = self._get(self.superadmin)
        trials = res.data["expiring_trials"]

        self.assertEqual(len(trials), 1)
        self.assertEqual(trials[0]["name"], "Trial Gym")
        self.assertLessEqual(trials[0]["days_left"], 5)

    def test_plan_distribution_groups_tenants_by_plan(self):
        res = self._get(self.superadmin)
        pro = next(p for p in res.data["plan_distribution"] if p["slug"] == "pro")

        self.assertEqual(pro["tenants"], 2)
        self.assertEqual(pro["name"], "Pro")

    def test_platform_user_without_the_module_is_denied(self):
        res = self._get(self.outsider)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_anonymous_access_is_rejected(self):
        res = self.client.get(OVERVIEW_URL, HTTP_HOST="testserver")
        self.assertIn(
            res.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )
