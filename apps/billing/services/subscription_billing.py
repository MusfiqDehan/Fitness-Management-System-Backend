"""Platform SaaS subscription billing helpers."""
from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django_tenants.utils import get_public_schema_name, schema_context

from apps.tenancy.models import PaymentGateway, PlatformPackage, PlatformSettings, TenantSubscriptionInvoice
from utils.currency import convert_currency

from apps.billing.services import get_gateway


def _sync_tenant_limits_from_package(tenant, package_slug: str) -> None:
    if tenant is None or not package_slug:
        return

    pkg = PlatformPackage.objects.filter(slug=package_slug).first()
    if pkg is None:
        return

    updated = []
    if tenant.max_users != pkg.max_users:
        tenant.max_users = pkg.max_users
        updated.append("max_users")
    if tenant.max_branches != pkg.max_branches:
        tenant.max_branches = pkg.max_branches
        updated.append("max_branches")

    for attr, pkg_attr in (
        ("max_members_per_branch", "max_members_per_branch"),
        ("max_trainers_per_branch", "max_trainers_per_branch"),
        ("max_employees_per_branch", "max_employees_per_branch"),
    ):
        tenant_val = getattr(tenant, attr, None)
        pkg_val = getattr(pkg, pkg_attr, None)
        if tenant_val != pkg_val:
            setattr(tenant, attr, pkg_val)
            updated.append(attr)

    if updated:
        tenant.save(update_fields=[*updated, "updated_at"])


def activate_tenant_subscription(invoice: TenantSubscriptionInvoice) -> None:
    """Activate tenant plan from a successful subscription invoice."""
    tenant = invoice.tenant
    if tenant is None:
        return

    tenant.is_trial = False
    tenant.status = "active"
    tenant.plan = invoice.package_slug
    tenant.subscription_start = timezone.now()
    tenant.subscription_end = invoice.period_end
    tenant.save(
        update_fields=[
            "is_trial",
            "status",
            "plan",
            "subscription_start",
            "subscription_end",
            "updated_at",
        ]
    )
    _sync_tenant_limits_from_package(tenant, invoice.package_slug)


def initiate_for_tenant(
    *,
    tenant,
    package_slug: str,
    billing_cycle: str,
    request,
    notify_channels: list[str] | None = None,
    initiated_by_platform: bool = False,
) -> tuple[str, str, TenantSubscriptionInvoice]:
    """Create pending invoice and initiate gateway. Returns (gateway_url, tran_id, invoice)."""
    public_schema = get_public_schema_name()
    with schema_context(public_schema):
        from apps.tenancy.models import Tenant as PublicTenant

        live_tenant = PublicTenant.objects.get(pk=tenant.pk)
        pkg = PlatformPackage.objects.filter(slug=package_slug, is_active=True).first()
        if pkg is None:
            raise ValueError(f"Package '{package_slug}' is not available.")

        if billing_cycle == "yearly":
            amount_usd = pkg.price_yearly
            period_days = 365
        else:
            amount_usd = pkg.price_monthly
            period_days = 30

        if amount_usd <= Decimal("0"):
            raise ValueError("Free plans cannot be processed as a payment.")

        gateway = PaymentGateway.objects.filter(is_default_for_subscriptions=True).first()
        if gateway is None or not (gateway.platform_credentials or {}):
            raise RuntimeError("No subscription payment gateway is configured.")

        ps = PlatformSettings.objects.filter(pk=1).first()
        target_currency = ps.default_currency if ps else "USD"
        amount = convert_currency(amount_usd, "USD", target_currency)

        prefix = "SUB" if not initiated_by_platform else "PLT"
        tran_id = f"{prefix}-{live_tenant.schema_name.upper()}-{uuid.uuid4().hex[:12].upper()}"
        now = timezone.now()
        gateway_response: dict = {}
        if notify_channels:
            gateway_response["notify_channels"] = list(notify_channels)

        invoice = TenantSubscriptionInvoice.objects.create(
            tenant=live_tenant,
            package_slug=pkg.slug,
            package_name=pkg.name,
            amount=amount,
            currency=target_currency,
            tran_id=tran_id,
            gateway_slug=gateway.slug,
            status=TenantSubscriptionInvoice.STATUS_PENDING,
            billing_cycle=billing_cycle,
            period_start=now,
            period_end=now + timedelta(days=period_days),
            is_trial=False,
            gateway_response=gateway_response,
        )

        backend_base = (
            (getattr(settings, "BACKEND_BASE_URL", "") or "").rstrip("/")
            or request.build_absolute_uri("/").rstrip("/")
        )
        svc = get_gateway(
            gateway.slug,
            credentials=gateway.platform_credentials,
            is_sandbox=gateway.is_sandbox,
            success_url=f"{backend_base}/api/v1/billing/subscription/success/",
            fail_url=f"{backend_base}/api/v1/billing/subscription/fail/",
            cancel_url=f"{backend_base}/api/v1/billing/subscription/cancel/",
            ipn_url=f"{backend_base}/api/v1/billing/subscription/ipn/",
        )
        result = svc.initiate(invoice)
        gateway_url = result.get("gateway_url", "")
        if not gateway_url:
            invoice.status = TenantSubscriptionInvoice.STATUS_CANCELLED
            invoice.save(update_fields=["status", "updated_at"])
            raise RuntimeError("Failed to initiate payment with the gateway.")

        return gateway_url, tran_id, invoice


def create_manual_subscription(
    *,
    tenant,
    package_slug: str,
    billing_cycle: str,
    reference_note: str,
    actor,
    amount_override: Decimal | None = None,
    period_start=None,
    period_end=None,
    notify_channels: list[str] | None = None,
) -> TenantSubscriptionInvoice:
    """Record an offline/manual subscription payment as success immediately."""
    public_schema = get_public_schema_name()
    with schema_context(public_schema):
        from apps.tenancy.models import Tenant as PublicTenant

        with transaction.atomic():
            live_tenant = PublicTenant.objects.select_for_update().get(pk=tenant.pk)
            pkg = PlatformPackage.objects.filter(slug=package_slug, is_active=True).first()
            if pkg is None:
                raise ValueError(f"Package '{package_slug}' is not available.")

            if billing_cycle == "yearly":
                amount_usd = pkg.price_yearly
                period_days = 365
            else:
                amount_usd = pkg.price_monthly
                period_days = 30

            ps = PlatformSettings.objects.filter(pk=1).first()
            target_currency = ps.default_currency if ps else "USD"
            amount = amount_override if amount_override is not None else convert_currency(amount_usd, "USD", target_currency)

            now = timezone.now()
            start = period_start or now
            end = period_end or (start + timedelta(days=period_days))

            tran_id = f"MAN-{live_tenant.schema_name.upper()}-{uuid.uuid4().hex[:12].upper()}"
            invoice = TenantSubscriptionInvoice.objects.create(
                tenant=live_tenant,
                package_slug=pkg.slug,
                package_name=pkg.name,
                amount=amount,
                currency=target_currency,
                tran_id=tran_id,
                gateway_slug="manual",
                status=TenantSubscriptionInvoice.STATUS_SUCCESS,
                billing_cycle=billing_cycle,
                period_start=start,
                period_end=end,
                is_trial=False,
                validated_at=now,
                gateway_response={
                    "reference_note": reference_note,
                    "created_by": getattr(actor, "pk", None),
                    "notify_channels": list(notify_channels or []),
                },
            )
            activate_tenant_subscription(invoice)
            return invoice


def recalc_tenant_subscription(tenant) -> None:
    """Recalculate tenant subscription from the latest success invoice, or clear plan fields."""
    public_schema = get_public_schema_name()
    with schema_context(public_schema):
        from apps.tenancy.models import Tenant as PublicTenant

        with transaction.atomic():
            live = PublicTenant.objects.select_for_update().get(pk=tenant.pk)
            latest = (
                TenantSubscriptionInvoice.objects.filter(
                    tenant=live,
                    status=TenantSubscriptionInvoice.STATUS_SUCCESS,
                )
                .order_by("-period_end", "-created_at")
                .first()
            )
            if latest:
                activate_tenant_subscription(latest)
            else:
                live.plan = ""
                live.subscription_start = None
                live.subscription_end = None
                live.save(
                    update_fields=[
                        "plan",
                        "subscription_start",
                        "subscription_end",
                        "updated_at",
                    ]
                )
