"""Stripe Checkout payment gateway implementation.

Uses Stripe-hosted Checkout Sessions for one-time payments, matching the
redirect flow used by SSLCommerz (initiate → redirect → validate on callback).
"""
from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import stripe
from django.conf import settings

from .base import AbstractPaymentGateway

logger = logging.getLogger(__name__)

# Currencies where Stripe expects the major unit (no cents).
# See https://docs.stripe.com/currencies#zero-decimal
_ZERO_DECIMAL_CURRENCIES = frozenset({
    "bif", "clp", "djf", "gnf", "jpy", "kmf", "krw", "mga",
    "pyg", "rwf", "ugx", "vnd", "vuv", "xaf", "xof", "xpf",
})


def _to_stripe_amount(amount: Decimal | float | int | str, currency: str) -> int:
    """Convert a major-unit amount to Stripe's integer amount."""
    value = Decimal(str(amount))
    currency_code = (currency or "usd").strip().lower()
    if currency_code in _ZERO_DECIMAL_CURRENCIES:
        return int(value.to_integral_value(rounding=ROUND_HALF_UP))
    return int((value * Decimal("100")).to_integral_value(rounding=ROUND_HALF_UP))


def _from_stripe_amount(amount: int | None, currency: str) -> Decimal:
    """Convert Stripe's integer amount back to a major-unit Decimal."""
    if amount is None:
        return Decimal("0")
    currency_code = (currency or "usd").strip().lower()
    if currency_code in _ZERO_DECIMAL_CURRENCIES:
        return Decimal(amount)
    return (Decimal(amount) / Decimal("100")).quantize(Decimal("0.01"))


def _append_query(url: str, **params: str) -> str:
    """Append query params to a URL, preserving existing ones.

    Leaves ``{CHECKOUT_SESSION_ID}`` unencoded so Stripe can substitute it.
    """
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update({k: v for k, v in params.items() if v is not None})
    encoded = urlencode(query)
    # Stripe requires the literal template token in success_url.
    encoded = encoded.replace("%7BCHECKOUT_SESSION_ID%7D", "{CHECKOUT_SESSION_ID}")
    encoded = encoded.replace("%7bCHECKOUT_SESSION_ID%7d", "{CHECKOUT_SESSION_ID}")
    return urlunparse(parsed._replace(query=encoded))


class StripeService(AbstractPaymentGateway):
    """Creates Checkout Sessions and validates them by session ID."""

    def __init__(
        self,
        secret_key: str,
        publishable_key: str = "",
        is_sandbox: bool = True,
        success_url: str = "",
        fail_url: str = "",
        cancel_url: str = "",
        ipn_url: str = "",
    ):
        self.secret_key = (secret_key or "").strip()
        self.publishable_key = (publishable_key or "").strip()
        self.is_sandbox = is_sandbox
        self.success_url = success_url
        self.fail_url = fail_url
        self.cancel_url = cancel_url
        self.ipn_url = ipn_url

        if not self.secret_key:
            raise ValueError("Stripe secret_key is required.")

        # Soft-check: warn when sandbox/live mode does not match key prefix.
        if self.is_sandbox and self.secret_key.startswith("sk_live_"):
            logger.warning("Stripe is_sandbox=True but a live secret key was provided.")
        if not self.is_sandbox and self.secret_key.startswith("sk_test_"):
            logger.warning("Stripe is_sandbox=False but a test secret key was provided.")

        stripe.api_key = self.secret_key
        api_version = getattr(settings, "STRIPE_API_VERSION", "") or ""
        if api_version:
            stripe.api_version = api_version

    def initiate(self, transaction) -> Dict[str, Any]:
        """Create a Stripe Checkout Session and return its hosted URL."""
        source_payment = getattr(transaction, "source_payment", None)
        tenant = getattr(transaction, "tenant", None)

        def _first_non_empty(*values: Any) -> str:
            for value in values:
                text = str(value or "").strip()
                if text:
                    return text
            return ""

        currency = (getattr(transaction, "currency", None) or "usd").strip().lower()
        amount = _to_stripe_amount(transaction.amount, currency)
        if amount <= 0:
            raise ValueError("Stripe amount must be greater than zero.")

        customer_email = _first_non_empty(
            source_payment.member.email if source_payment and getattr(source_payment, "member", None) else "",
            getattr(transaction, "customer_email", ""),
            getattr(tenant, "billing_email", ""),
            getattr(tenant, "owner_email", ""),
        )
        product_name = _first_non_empty(
            getattr(transaction, "package_name", ""),
            "Gym Membership" if source_payment else "Subscription",
        )
        description = _first_non_empty(
            getattr(transaction, "tran_id", ""),
            product_name,
        )

        success_url = _append_query(
            self.success_url,
            tran_id=str(transaction.tran_id),
            session_id="{CHECKOUT_SESSION_ID}",
        )
        cancel_url = _append_query(
            self.cancel_url or self.fail_url,
            tran_id=str(transaction.tran_id),
        )

        metadata = {
            "tran_id": str(transaction.tran_id),
            "gateway": "stripe",
        }
        if source_payment is not None and getattr(source_payment, "id", None):
            metadata["payment_id"] = str(source_payment.id)

        session_params: Dict[str, Any] = {
            "mode": "payment",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "line_items": [
                {
                    "quantity": 1,
                    "price_data": {
                        "currency": currency,
                        "unit_amount": amount,
                        "product_data": {
                            "name": product_name[:120],
                            "description": description[:500] or None,
                        },
                    },
                }
            ],
            "client_reference_id": str(transaction.tran_id)[:200],
            "metadata": metadata,
            "payment_intent_data": {"metadata": metadata},
        }
        # Drop None description so Stripe does not reject empty product_data.
        if session_params["line_items"][0]["price_data"]["product_data"].get("description") is None:
            session_params["line_items"][0]["price_data"]["product_data"].pop("description", None)

        if customer_email:
            session_params["customer_email"] = customer_email

        try:
            session = stripe.checkout.Session.create(**session_params)
        except stripe.StripeError as exc:
            logger.error("Stripe Checkout Session create failed: %s", exc)
            raise ValueError(f"Stripe session init failed: {exc}") from exc

        gateway_url = getattr(session, "url", None)
        if not gateway_url:
            raise ValueError("Stripe did not return a checkout URL.")

        return {
            "gateway_url": gateway_url,
            "raw": {
                "id": session.id,
                "payment_status": session.payment_status,
                "status": session.status,
                "url": gateway_url,
                "publishable_key": self.publishable_key,
            },
        }

    def validate(self, val_id: str) -> Dict[str, Any]:
        """Retrieve a Checkout Session by ID and map to the shared VALID shape."""
        session_id = (val_id or "").strip()
        if not session_id:
            raise ValueError("Stripe session id (val_id) is required.")

        try:
            session = stripe.checkout.Session.retrieve(session_id)
        except stripe.StripeError as exc:
            logger.error("Stripe session retrieve failed: %s", exc)
            raise ValueError(f"Stripe validation failed: {exc}") from exc

        currency = (session.currency or "usd").lower()
        amount_total = _from_stripe_amount(session.amount_total, currency)
        payment_status = (session.payment_status or "").lower()
        status = (session.status or "").lower()

        is_paid = payment_status == "paid" and status in ("complete", "open")
        # Prefer complete+paid; still accept paid when status is complete.
        if payment_status == "paid" and status == "complete":
            is_paid = True
        elif payment_status == "paid":
            is_paid = True

        return {
            "status": "VALID" if is_paid else "FAILED",
            "amount": str(amount_total),
            "currency": currency.upper(),
            "session_id": session.id,
            "payment_status": payment_status,
            "session_status": status,
            "tran_id": (session.client_reference_id or (session.metadata or {}).get("tran_id") or ""),
            "raw": {
                "id": session.id,
                "payment_intent": session.payment_intent,
                "payment_status": payment_status,
                "status": status,
                "amount_total": session.amount_total,
                "currency": currency,
                "metadata": dict(session.metadata or {}),
            },
        }
