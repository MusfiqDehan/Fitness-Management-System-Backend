"""Tests for subscription summary, manual/gateway subscription, notifications, platform CRUD."""
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import override_settings
from django.utils import timezone
from django_tenants.utils import schema_context
from rest_framework import status
from rest_framework.test import APITestCase, APIRequestFactory, force_authenticate

from apps.billing.services.member_renewal import apply_paid_payment
from apps.billing.services.payment_confirmation import (
    dispatch_member_payment,
    dispatch_subscription_invoice,
)
from apps.billing.views import SubscriptionSummaryView
from apps.identity.models import User
from apps.membership.models import Member, MemberPackage, Payment
from apps.reminder.models import Notification
from apps.tenancy.models import (
    Domain,
    Feature,
    PaymentGateway,
    PlatformPackage,
    PlatformRole,
    PlatformRolePermission,
    PlatformSettings,
    PlatformUserRole,
    Tenant,
    TenantFeatureFlag,
    TenantSubscriptionInvoice,
)
from apps.tenancy.test_feature_registry import FeatureRegistryConsistencyTests


@override_settings(PUBLIC_DOMAIN="testserver")
class PlatformBillingTestBase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        with schema_context("public"):
            cls.public, _ = Tenant.objects.get_or_create(
                schema_name="public",
                defaults=dict(
                    name="Public",
                    slug="public",
                    code="PLATBILL01",
                    owner_email="root@platbill.test",
                    billing_email="root@platbill.test",
                    status="active",
                ),
            )
            Domain.objects.get_or_create(
                domain="testserver",
                tenant=cls.public,
                defaults={"is_primary": True},
            )
            cls.platform_admin = User.objects.create_superuser(
                email="root@platbill.test",
                password="StrongPass123!",
                tenant=cls.public,
            )
            cls.viewer = User.objects.create_user(
                email="viewer@platbill.test",
                password="StrongPass123!",
                tenant=cls.public,
            )
            cls.viewer.is_staff = True
            cls.viewer.save(update_fields=["is_staff"])
            viewer_role = PlatformRole.objects.create(name="Payments Viewer", slug="payments-viewer")
            PlatformRolePermission.objects.create(
                role=viewer_role,
                module_key="platform.payments",
                permission_level="view",
            )
            PlatformUserRole.objects.create(user=cls.viewer, role=viewer_role)

            cls.tenant = Tenant.objects.create(
                schema_name="platbill_tenant",
                name="PlatBill Tenant",
                slug="platbill",
                code="PLATB001",
                owner_email="admin@platbill.test",
                billing_email="admin@platbill.test",
                status="active",
                plan="growth",
            )
            Domain.objects.create(domain="platbill.testserver", tenant=cls.tenant, is_primary=True)
            PlatformSettings.objects.get_or_create(pk=1, defaults={"default_currency": "USD"})
            PlatformPackage.objects.get_or_create(
                slug="growth",
                defaults={
                    "name": "Growth",
                    "price_monthly": Decimal("100"),
                    "price_yearly": Decimal("1000"),
                    "is_active": True,
                    "is_public": True,
                },
            )
            cls.gateway, _ = PaymentGateway.objects.get_or_create(
                slug="sslcommerz",
                defaults={
                    "name": "SSLCommerz",
                    "is_default_for_subscriptions": True,
                    "platform_credentials": {"store_id": "test", "store_passwd": "test"},
                },
            )
            if not cls.gateway.is_default_for_subscriptions:
                cls.gateway.is_default_for_subscriptions = True
                cls.gateway.platform_credentials = {"store_id": "test", "store_passwd": "test"}
                cls.gateway.save()

    def _create_invoice(self, **kwargs):
        defaults = {
            "tenant": self.tenant,
            "package_slug": "growth",
            "package_name": "Growth",
            "amount": Decimal("100"),
            "currency": "USD",
            "tran_id": f"MAN-TEST-{timezone.now().timestamp()}",
            "gateway_slug": "manual",
            "status": TenantSubscriptionInvoice.STATUS_SUCCESS,
            "billing_cycle": "monthly",
            "period_start": timezone.now(),
            "period_end": timezone.now() + timedelta(days=30),
        }
        defaults.update(kwargs)
        with schema_context("public"):
            return TenantSubscriptionInvoice.objects.create(**defaults)


class FeatureRegistrySubscriptionsTests(FeatureRegistryConsistencyTests):
    def test_subscriptions_key_in_registry(self):
        from apps.access.management.commands.seed_tenant_roles import FULL_ACCESS_FEATURE_KEYS
        from apps.tenancy.feature_registry import iter_tenant_leaf_keys

        self.assertIn("subscriptions", FULL_ACCESS_FEATURE_KEYS)
        self.assertIn("subscriptions", iter_tenant_leaf_keys())


class MemberRenewalServiceTests(APITestCase):
    def setUp(self):
        with schema_context("public"):
            self.public = Tenant.objects.create(
                schema_name="public",
                name="Public",
                slug="public",
                code="PUBSUB01",
                owner_email="root@renewal.test",
                billing_email="root@renewal.test",
                status="active",
            )
            Domain.objects.get_or_create(domain="testserver", tenant=self.public, defaults={"is_primary": True})
            self.tenant = Tenant.objects.create(
                schema_name="renewal_test",
                name="Renewal Tenant",
                slug="renewal",
                code="RENEW001",
                owner_email="admin@renewal.test",
                billing_email="admin@renewal.test",
                status="active",
                plan="growth",
            )
            Domain.objects.create(domain="renewal.testserver", tenant=self.tenant, is_primary=True)
            PlatformSettings.objects.get_or_create(pk=1, defaults={"default_currency": "USD"})

        with schema_context(self.tenant.schema_name):
            self.admin = User.objects.create_superuser(
                email="admin@renewal.test",
                password="StrongPass123!",
                tenant=self.tenant,
            )
            self.pkg = MemberPackage.objects.create(
                name="Monthly",
                package_type="monthly",
                duration_in_days=30,
                price=Decimal("1000"),
            )
            self.member = Member.objects.create(
                full_name="Test Member",
                phone_number="01700000001",
                email="member@renewal.test",
                membership_type="package",
                member_package=self.pkg,
                start_date=date.today(),
                end_date=date.today() + timedelta(days=5),
                payment_status="unpaid",
            )
            self.payment = Payment.objects.create(
                member=self.member,
                payment_type="package",
                amount=Decimal("1000"),
                payment_method="cash",
                payment_status=Payment.STATUS_PAID,
                payment_date=timezone.now(),
            )

    def test_apply_paid_payment_extends_end_date(self):
        with schema_context(self.tenant.schema_name):
            old_end = self.member.end_date
            apply_paid_payment(self.payment, previous_status=Payment.STATUS_DUE)
            self.member.refresh_from_db()
            self.assertEqual(self.member.payment_status, "paid")
            self.assertGreater(self.member.end_date, old_end)

    def test_apply_paid_payment_skips_when_already_paid(self):
        with schema_context(self.tenant.schema_name):
            old_end = self.member.end_date
            apply_paid_payment(self.payment, previous_status=Payment.STATUS_PAID)
            self.member.refresh_from_db()
            self.assertEqual(self.member.end_date, old_end)


class SubscriptionSummaryViewTests(APITestCase):
    def setUp(self):
        with schema_context("public"):
            self.public = Tenant.objects.create(
                schema_name="public",
                name="Public",
                slug="public",
                code="PUBSUM01",
                owner_email="root@summary.test",
                billing_email="root@summary.test",
                status="active",
            )
            Domain.objects.get_or_create(domain="testserver", tenant=self.public, defaults={"is_primary": True})
            self.tenant = Tenant.objects.create(
                schema_name="summary_test",
                name="Summary Tenant",
                slug="summary",
                code="SUMM0001",
                owner_email="admin@summary.test",
                billing_email="admin@summary.test",
                status="active",
                plan="growth",
                is_trial=False,
                subscription_end=timezone.now() + timedelta(days=10),
            )
            Domain.objects.create(domain="summary.testserver", tenant=self.tenant, is_primary=True)
            PlatformSettings.objects.get_or_create(pk=1, defaults={"default_currency": "USD"})
            PlatformPackage.objects.get_or_create(
                slug="growth",
                defaults={
                    "name": "Growth",
                    "price_monthly": Decimal("100"),
                    "price_yearly": Decimal("1000"),
                    "is_active": True,
                    "is_public": True,
                },
            )
            feature, _ = Feature.objects.get_or_create(key="subscriptions", defaults={"name": "Subscriptions"})
            TenantFeatureFlag.objects.get_or_create(
                tenant=self.tenant,
                feature=feature,
                defaults={"is_enabled": True, "source": TenantFeatureFlag.SOURCE_OVERRIDE},
            )

        with schema_context(self.tenant.schema_name):
            self.admin = User.objects.create_superuser(
                email="admin@summary.test",
                password="StrongPass123!",
                tenant=self.tenant,
            )
            self.staff = User.objects.create_user(
                email="staff@summary.test",
                password="StrongPass123!",
                tenant=self.tenant,
                role="student",
            )

        self.factory = APIRequestFactory()

    def _get_summary(self, user):
        request = self.factory.get("/api/v1/billing/subscription/summary/")
        request.tenant = self.tenant
        force_authenticate(request, user=user)
        with schema_context(self.tenant.schema_name):
            return SubscriptionSummaryView.as_view()(request)

    def test_admin_can_view_summary(self):
        response = self._get_summary(self.admin)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("total_paid", response.data)
        self.assertIn("upcoming_renewal_date", response.data)

    def test_non_admin_denied(self):
        response = self._get_summary(self.staff)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class PlatformManualSubscriptionApiTests(PlatformBillingTestBase):
    def test_manual_create_success(self):
        self.client.force_authenticate(user=self.platform_admin)
        res = self.client.post(
            "/api/v1/billing/subscription/payments/manual/",
            {
                "tenant_id": self.tenant.id,
                "package_slug": "growth",
                "billing_cycle": "monthly",
                "reference_note": "Bank transfer ref 123",
            },
            format="json",
            HTTP_HOST="testserver",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["gateway_slug"], "manual")
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.plan, "growth")

    def test_manual_create_missing_note(self):
        self.client.force_authenticate(user=self.platform_admin)
        res = self.client.post(
            "/api/v1/billing/subscription/payments/manual/",
            {
                "tenant_id": self.tenant.id,
                "package_slug": "growth",
                "billing_cycle": "monthly",
            },
            format="json",
            HTTP_HOST="testserver",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_manual_create_viewer_forbidden(self):
        self.client.force_authenticate(user=self.viewer)
        res = self.client.post(
            "/api/v1/billing/subscription/payments/manual/",
            {
                "tenant_id": self.tenant.id,
                "package_slug": "growth",
                "billing_cycle": "monthly",
                "reference_note": "note",
            },
            format="json",
            HTTP_HOST="testserver",
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)


class PlatformGatewaySubscriptionApiTests(PlatformBillingTestBase):
    @patch("apps.billing.services.subscription_billing.get_gateway")
    def test_gateway_initiate_success(self, mock_get_gateway):
        mock_svc = MagicMock()
        mock_svc.initiate.return_value = {"gateway_url": "https://gateway.test/pay"}
        mock_get_gateway.return_value = mock_svc

        self.client.force_authenticate(user=self.platform_admin)
        res = self.client.post(
            "/api/v1/billing/subscription/payments/gateway/",
            {
                "tenant_id": self.tenant.id,
                "package_slug": "growth",
                "billing_cycle": "monthly",
                "notify_channels": ["email"],
            },
            format="json",
            HTTP_HOST="testserver",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("gateway_url", res.data)
        self.assertIn("tran_id", res.data)

    def test_gateway_no_gateway_configured(self):
        with schema_context("public"):
            PaymentGateway.objects.filter(is_default_for_subscriptions=True).update(
                is_default_for_subscriptions=False
            )

        self.client.force_authenticate(user=self.platform_admin)
        res = self.client.post(
            "/api/v1/billing/subscription/payments/gateway/",
            {
                "tenant_id": self.tenant.id,
                "package_slug": "growth",
                "billing_cycle": "monthly",
            },
            format="json",
            HTTP_HOST="testserver",
        )
        self.assertEqual(res.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)

        with schema_context("public"):
            self.gateway.is_default_for_subscriptions = True
            self.gateway.save()


class PaymentConfirmationServiceTests(APITestCase):
    def setUp(self):
        with schema_context("public"):
            self.public = Tenant.objects.create(
                schema_name="public",
                name="Public",
                slug="public",
                code="PUBCONF01",
                owner_email="root@conf.test",
                billing_email="root@conf.test",
                status="active",
            )
            Domain.objects.get_or_create(domain="testserver", tenant=self.public, defaults={"is_primary": True})
            self.tenant = Tenant.objects.create(
                schema_name="conf_test",
                name="Conf Tenant",
                slug="conf",
                code="CONF0001",
                owner_email="admin@conf.test",
                billing_email="billing@conf.test",
                status="active",
            )
            Domain.objects.create(domain="conf.testserver", tenant=self.tenant, is_primary=True)

        with schema_context(self.tenant.schema_name):
            self.member = Member.objects.create(
                full_name="Pay Member",
                phone_number="01700000099",
                email="member@conf.test",
                membership_type="package",
                start_date=date.today(),
            )
            self.payment = Payment.objects.create(
                member=self.member,
                payment_type="package",
                amount=Decimal("500"),
                payment_method="cash",
                payment_status=Payment.STATUS_PAID,
                payment_date=timezone.now(),
            )

    @patch("apps.billing.services.payment_confirmation.create_notification")
    @patch("apps.billing.services.payment_confirmation.EmailMultiAlternatives")
    @patch("apps.billing.views._render_payment_invoice_pdf", return_value=b"%PDF")
    def test_dispatch_member_payment_email_and_in_app(self, _pdf, mock_email_cls, mock_notify):
        with schema_context(self.tenant.schema_name):
            dispatch_member_payment(self.payment, ["email", "in_app"], tenant=self.tenant)
        mock_email_cls.return_value.send.assert_called_once()
        self.assertGreaterEqual(mock_notify.call_count, 1)

    @patch("apps.billing.services.payment_confirmation.create_notification")
    @patch("apps.billing.services.payment_confirmation.EmailMultiAlternatives")
    def test_dispatch_member_payment_skips_email_without_address(self, mock_email_cls, mock_notify):
        with schema_context(self.tenant.schema_name):
            self.member.email = ""
            self.member.save(update_fields=["email"])
            dispatch_member_payment(self.payment, ["email"], tenant=self.tenant)
        mock_email_cls.return_value.send.assert_not_called()

    @patch("apps.billing.services.payment_confirmation.create_notification")
    @patch("apps.billing.services.payment_confirmation.EmailMultiAlternatives")
    @patch("apps.billing.views._render_subscription_invoice_pdf", return_value=b"%PDF")
    def test_dispatch_subscription_invoice(self, _pdf, mock_email_cls, mock_notify):
        with schema_context("public"):
            invoice = TenantSubscriptionInvoice.objects.create(
                tenant=self.tenant,
                package_slug="growth",
                package_name="Growth",
                amount=Decimal("100"),
                currency="USD",
                tran_id="MAN-SUB-001",
                gateway_slug="manual",
                status=TenantSubscriptionInvoice.STATUS_SUCCESS,
            )
            dispatch_subscription_invoice(invoice, ["email", "in_app"])
        mock_email_cls.return_value.send.assert_called_once()
        mock_notify.assert_called_once()
        args, kwargs = mock_notify.call_args
        self.assertEqual(kwargs.get("notification_type"), Notification.SUBSCRIPTION_PAYMENT_CONFIRMED)


class PlatformSubscriptionPaymentsListTests(PlatformBillingTestBase):
    def setUp(self):
        super().setUp()
        with schema_context("public"):
            for i in range(15):
                TenantSubscriptionInvoice.objects.create(
                    tenant=self.tenant,
                    package_slug="growth",
                    package_name="Growth",
                    amount=Decimal("10") + i,
                    currency="USD",
                    tran_id=f"LIST-INV-{i:03d}",
                    gateway_slug="manual" if i % 2 == 0 else "sslcommerz",
                    status=TenantSubscriptionInvoice.STATUS_SUCCESS if i % 3 else TenantSubscriptionInvoice.STATUS_PENDING,
                    billing_cycle="monthly",
                )

    def test_paginated_list_metadata(self):
        self.client.force_authenticate(user=self.platform_admin)
        res = self.client.get(
            "/api/v1/billing/subscription/payments/?page=2&page_size=5",
            HTTP_HOST="testserver",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["count"], 15)
        self.assertEqual(res.data["total_pages"], 3)
        self.assertEqual(len(res.data["results"]), 5)
        self.assertEqual(res.data["stats"]["total_payments"], 15)

    def test_search_filter(self):
        self.client.force_authenticate(user=self.platform_admin)
        res = self.client.get(
            "/api/v1/billing/subscription/payments/?search=LIST-INV-001",
            HTTP_HOST="testserver",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["count"], 1)

    def test_gateway_and_ordering_filters(self):
        self.client.force_authenticate(user=self.platform_admin)
        res = self.client.get(
            "/api/v1/billing/subscription/payments/?gateway_slug=manual&ordering=-amount",
            HTTP_HOST="testserver",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        amounts = [Decimal(row["amount"]) for row in res.data["results"]]
        self.assertEqual(amounts, sorted(amounts, reverse=True))


class PlatformSubscriptionPaymentCrudTests(PlatformBillingTestBase):
    def test_patch_manual_invoice(self):
        invoice = self._create_invoice(amount=Decimal("150"))
        self.client.force_authenticate(user=self.platform_admin)
        res = self.client.patch(
            f"/api/v1/billing/subscription/payments/{invoice.id}/",
            {"amount": "200.00", "reference_note": "Updated note"},
            format="json",
            HTTP_HOST="testserver",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["amount"], "200.00")

    def test_patch_pending_gateway_restricted(self):
        invoice = self._create_invoice(
            tran_id="PEND-GW-001",
            gateway_slug="sslcommerz",
            status=TenantSubscriptionInvoice.STATUS_PENDING,
        )
        self.client.force_authenticate(user=self.platform_admin)
        res = self.client.patch(
            f"/api/v1/billing/subscription/payments/{invoice.id}/",
            {"amount": "999.00"},
            format="json",
            HTTP_HOST="testserver",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_patch_viewer_forbidden(self):
        invoice = self._create_invoice(tran_id="VIEW-PATCH-001")
        self.client.force_authenticate(user=self.viewer)
        res = self.client.patch(
            f"/api/v1/billing/subscription/payments/{invoice.id}/",
            {"amount": "50.00"},
            format="json",
            HTTP_HOST="testserver",
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_manual_invoice(self):
        invoice = self._create_invoice(tran_id="DEL-MAN-001")
        self.client.force_authenticate(user=self.platform_admin)
        res = self.client.delete(
            f"/api/v1/billing/subscription/payments/{invoice.id}/",
            HTTP_HOST="testserver",
        )
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)
        with schema_context("public"):
            self.assertFalse(TenantSubscriptionInvoice.objects.filter(pk=invoice.id).exists())

    def test_delete_pending_gateway_blocked(self):
        invoice = self._create_invoice(
            tran_id="DEL-PEND-001",
            gateway_slug="sslcommerz",
            status=TenantSubscriptionInvoice.STATUS_PENDING,
        )
        self.client.force_authenticate(user=self.platform_admin)
        res = self.client.delete(
            f"/api/v1/billing/subscription/payments/{invoice.id}/",
            HTTP_HOST="testserver",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_delete_success_requires_confirmation(self):
        invoice = self._create_invoice(tran_id="DEL-SUC-001")
        self.client.force_authenticate(user=self.platform_admin)
        res = self.client.delete(
            f"/api/v1/billing/subscription/payments/{invoice.id}/",
            HTTP_HOST="testserver",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

        res2 = self.client.delete(
            f"/api/v1/billing/subscription/payments/{invoice.id}/?confirm_success_delete=true",
            HTTP_HOST="testserver",
        )
        self.assertEqual(res2.status_code, status.HTTP_204_NO_CONTENT)
