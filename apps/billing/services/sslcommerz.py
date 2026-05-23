"""SSLCommerz payment gateway implementation.

Mirrors the pattern in demo-sslcommerz-integration but adapted
for multi-tenant use with per-tenant credentials.
"""
import logging
from typing import Any, Dict

import requests

from .base import AbstractPaymentGateway

logger = logging.getLogger(__name__)

SANDBOX_BASE = "https://sandbox.sslcommerz.com"
LIVE_BASE = "https://securepay.sslcommerz.com"

SESSION_API = "gwprocess/v4/api.php"
VALIDATE_API = "validator/api/validationserverAPI.php"


class SSLCommerzService(AbstractPaymentGateway):
    """Calls the SSLCommerz session-init and validation APIs."""

    def __init__(self, store_id: str, store_password: str, is_sandbox: bool,
                 success_url: str, fail_url: str, cancel_url: str, ipn_url: str):
        self.store_id = store_id
        self.store_password = store_password
        self.is_sandbox = is_sandbox
        self._base = SANDBOX_BASE if is_sandbox else LIVE_BASE
        self.success_url = success_url
        self.fail_url = fail_url
        self.cancel_url = cancel_url
        self.ipn_url = ipn_url

    def initiate(self, transaction) -> Dict[str, Any]:
        """POST to SSLCommerz session-init API and return the gateway_url."""
        source_payment = getattr(transaction, "source_payment", None)

        payload = {
            "store_id": self.store_id,
            "store_passwd": self.store_password,
            "total_amount": str(transaction.amount),
            "currency": transaction.currency,
            "tran_id": transaction.tran_id,
            "success_url": self.success_url,
            "fail_url": self.fail_url,
            "cancel_url": self.cancel_url,
            "ipn_url": self.ipn_url,
            # Customer info (pulled from the linked payment's member when available,
            # or from a tenant object for subscription invoices)
            "cus_name": (
                source_payment.member.full_name
                if source_payment and getattr(source_payment, "member", None)
                else getattr(getattr(transaction, "tenant", None), "name", "Customer") or "Customer"
            ),
            "cus_email": (
                source_payment.member.email
                if source_payment and getattr(source_payment, "member", None)
                else getattr(getattr(transaction, "tenant", None), "billing_email", "") or ""
            ),
            "cus_phone": (
                source_payment.member.phone_number
                if source_payment and getattr(source_payment, "member", None)
                else ""
            ),
            "cus_add1": "N/A",
            "cus_city": "Dhaka",
            "cus_country": "Bangladesh",
            "shipping_method": "NO",
            "product_name": "Gym Membership",
            "product_category": "Service",
            "product_profile": "service",
        }

        url = f"{self._base}/{SESSION_API}"
        try:
            response = requests.post(url, data=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            logger.error("SSLCommerz session init failed: %s", exc)
            raise ValueError(f"SSLCommerz session init failed: {exc}") from exc

        if data.get("status") != "SUCCESS":
            logger.error("SSLCommerz session init error: %s", data)
            raise ValueError(data.get("failedreason") or "SSLCommerz session init failed.")

        gateway_url = data.get("GatewayPageURL") or data.get("redirectGatewayURL")
        if not gateway_url:
            raise ValueError("SSLCommerz did not return a gateway URL.")

        return {"gateway_url": gateway_url, "raw": data}

    def validate(self, val_id: str) -> Dict[str, Any]:
        """GET SSLCommerz validation endpoint to confirm a transaction."""
        url = f"{self._base}/{VALIDATE_API}"
        params = {
            "val_id": val_id,
            "store_id": self.store_id,
            "store_passwd": self.store_password,
            "format": "json",
        }
        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            logger.error("SSLCommerz validation failed: %s", exc)
            raise ValueError(f"SSLCommerz validation failed: {exc}") from exc
