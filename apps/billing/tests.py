from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from apps.tenancy.models import PaymentGateway
from .services.sslcommerz import SSLCommerzService
from .views import (
    _build_tenant_frontend_base_url,
    _build_tenant_backend_base_url,
    _is_gateway_credentials_complete,
    _payment_result_redirect_url,
)


class BillingGatewayHelperTests(SimpleTestCase):
    def test_credentials_complete_requires_all_required_keys(self):
        gateway = PaymentGateway(
            slug="sslcommerz",
            name="SSLCOMMERZ",
            config_schema=[
                {"key": "store_id", "required": True},
                {"key": "store_password", "required": True},
                {"key": "use_sandbox", "required": False},
            ],
        )

        self.assertFalse(
            _is_gateway_credentials_complete(
                gateway,
                {"store_id": "demo", "store_password": ""},
            )
        )

        self.assertTrue(
            _is_gateway_credentials_complete(
                gateway,
                {"store_id": "demo", "store_password": "secret"},
            )
        )

    @override_settings(BACKEND_BASE_URL="http://localhost:8021")
    def test_tenant_backend_base_url_uses_tenant_domain_and_backend_port(self):
        request = MagicMock()
        request.build_absolute_uri.return_value = "http://localhost:5174/"
        request.scheme = "http"

        tenant = MagicMock()
        domains_qs = MagicMock()
        values_qs = MagicMock()
        values_qs.first.return_value = "gym-alpha.localhost"
        domains_qs.values_list.return_value = values_qs
        tenant.domains.filter.return_value = domains_qs
        request.tenant = tenant

        self.assertEqual(
            _build_tenant_backend_base_url(request),
            "http://gym-alpha.localhost:8021",
        )

    @override_settings(BACKEND_BASE_URL="")
    def test_tenant_backend_base_url_falls_back_to_tenant_domain_when_base_missing(self):
        request = MagicMock()
        request.build_absolute_uri.return_value = "http://localhost:5174/"
        request.scheme = "https"

        tenant = MagicMock()
        domains_qs = MagicMock()
        values_qs = MagicMock()
        values_qs.first.return_value = "tenant.example.com"
        domains_qs.values_list.return_value = values_qs
        tenant.domains.filter.return_value = domains_qs
        request.tenant = tenant

        self.assertEqual(
            _build_tenant_backend_base_url(request),
            "https://tenant.example.com",
        )

    @override_settings(FRONTEND_BASE_URL="http://localhost:5174", PUBLIC_FRONTEND_URL="http://tenant.localhost:5174")
    def test_payment_result_redirect_uses_public_register_for_public_signup_flow(self):
        request = MagicMock()
        request.tenant = None
        tx = MagicMock()
        tx.gateway_response = {"flow": "public_member_signup"}

        self.assertEqual(
            _payment_result_redirect_url(request, tx, "success", "TXN-123"),
            "http://localhost:5174/register?payment_status=success&tran_id=TXN-123",
        )

    @override_settings(FRONTEND_BASE_URL="http://localhost:5174", PUBLIC_FRONTEND_URL="http://tenant.localhost:5174")
    def test_payment_result_redirect_defaults_to_dashboard_payments_flow(self):
        request = MagicMock()
        request.tenant = None
        tx = MagicMock()
        tx.gateway_response = {}

        self.assertEqual(
            _payment_result_redirect_url(request, tx, "fail", "TXN-999"),
            "http://localhost:5174/payments/fail?tran_id=TXN-999",
        )

    @override_settings(FRONTEND_BASE_URL="http://localhost:5174", PUBLIC_FRONTEND_URL="http://tenant.localhost:5174")
    def test_payment_result_redirect_uses_public_register_for_pubreg_tran_id(self):
        request = MagicMock()
        request.tenant = None
        tx = MagicMock()
        tx.gateway_response = {}

        self.assertEqual(
            _payment_result_redirect_url(request, tx, "success", "PUBREG-69-DB4CBD80"),
            "http://localhost:5174/register?payment_status=success&tran_id=PUBREG-69-DB4CBD80",
        )

    @override_settings(TENANT_FRONTEND_SCHEME="http", TENANT_FRONTEND_PORT="5174")
    def test_build_tenant_frontend_base_url_uses_tenant_primary_domain(self):
        request = MagicMock()
        tenant = MagicMock()
        tenant.schema_name = "hello9"
        domains_qs = MagicMock()
        values_qs = MagicMock()
        values_qs.first.return_value = "hello9.localhost"
        domains_qs.values_list.return_value = values_qs
        tenant.domains.filter.return_value = domains_qs
        request.tenant = tenant

        self.assertEqual(
            _build_tenant_frontend_base_url(request),
            "http://hello9.localhost:5174",
        )


class SSLCommerzServiceTests(SimpleTestCase):
    def _service(self) -> SSLCommerzService:
        return SSLCommerzService(
            store_id="demo",
            store_password="demo",
            is_sandbox=True,
            success_url="http://localhost/success",
            fail_url="http://localhost/fail",
            cancel_url="http://localhost/cancel",
            ipn_url="http://localhost/ipn",
        )

    @patch("apps.billing.services.sslcommerz.requests.post")
    def test_initiate_uses_transaction_customer_phone_for_subscription_invoice(self, mock_post):
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "status": "SUCCESS",
            "GatewayPageURL": "https://sandbox.sslcommerz.com/EasyCheckout/test",
        }
        mock_post.return_value = response

        transaction = MagicMock()
        transaction.amount = "3490.00"
        transaction.currency = "BDT"
        transaction.tran_id = "SUB-TEST-123"
        transaction.source_payment = None
        transaction.customer_phone = "01710000000"
        transaction.contact_phone = ""
        transaction.customer_email = "owner@example.com"
        transaction.customer_name = "Owner"
        transaction.tenant = MagicMock()
        transaction.tenant.name = "Growth Gym"
        transaction.tenant.billing_email = "owner@example.com"
        transaction.tenant.owner_email = "owner@example.com"
        transaction.tenant.metadata = {}

        self._service().initiate(transaction)

        payload = mock_post.call_args.kwargs["data"]
        self.assertEqual(payload["cus_phone"], "01710000000")

    @override_settings(SSLCOMMERZ_FALLBACK_PHONE="01700000000")
    @patch("apps.billing.services.sslcommerz.requests.post")
    def test_initiate_uses_fallback_phone_when_all_sources_missing(self, mock_post):
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "status": "SUCCESS",
            "GatewayPageURL": "https://sandbox.sslcommerz.com/EasyCheckout/test",
        }
        mock_post.return_value = response

        transaction = MagicMock()
        transaction.amount = "3490.00"
        transaction.currency = "BDT"
        transaction.tran_id = "SUB-TEST-456"
        transaction.source_payment = None
        transaction.customer_phone = ""
        transaction.contact_phone = ""
        transaction.customer_email = "owner@example.com"
        transaction.customer_name = "Owner"
        transaction.tenant = MagicMock()
        transaction.tenant.name = "Growth Gym"
        transaction.tenant.billing_email = "owner@example.com"
        transaction.tenant.owner_email = "owner@example.com"
        transaction.tenant.metadata = {}

        self._service().initiate(transaction)

        payload = mock_post.call_args.kwargs["data"]
        self.assertEqual(payload["cus_phone"], "01700000000")
