"""Platform SaaS subscription billing helpers."""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django_tenants.utils import get_public_schema_name, schema_context

from apps.tenancy.models import PaymentGateway, PlatformPackage, PlatformSettings, TenantSubscriptionInvoice
from utils.currency import convert_currency

from apps.billing.services import get_gateway


def compute_final_amount(
    base_amount: Decimal,
    adjustment_type: str,
    adjustment_amount: Decimal | None,
) -> Decimal:
    """Return non-negative final charge from base + optional adjustment."""
    base = Decimal(base_amount or 0)
    adj = Decimal(adjustment_amount or 0)
    if adjustment_type == TenantSubscriptionInvoice.ADJUSTMENT_ADDITION:
        final = base + adj
    elif adjustment_type == TenantSubscriptionInvoice.ADJUSTMENT_DEDUCTION:
        final = base - adj
    else:
        final = base
    return max(final, Decimal("0"))


def subscription_payment_type_label(payment_type: str) -> str:
    labels = dict(TenantSubscriptionInvoice.PAYMENT_TYPE_CHOICES)
    return labels.get(payment_type, payment_type.replace("_", " ").title())


def subscription_invoice_description(invoice: TenantSubscriptionInvoice) -> str:
    if invoice.payment_type == TenantSubscriptionInvoice.PAYMENT_TYPE_OTHER:
        return (invoice.custom_label or "Other").strip()
    if invoice.payment_type == TenantSubscriptionInvoice.PAYMENT_TYPE_SETUP_FEE:
        return "Setup Fee"
    return invoice.package_name or invoice.package_slug or "Package"


def subscription_invoice_original_price(invoice: TenantSubscriptionInvoice) -> Decimal:
    if invoice.base_amount is not None:
        return Decimal(invoice.base_amount)
    return Decimal(invoice.amount)


def subscription_invoice_format_money(invoice: TenantSubscriptionInvoice, amount: Decimal) -> str:
    return f"{invoice.currency} {amount:,.2f}"


def subscription_invoice_price_breakdown(invoice: TenantSubscriptionInvoice) -> dict[str, str]:
    """Human-readable original price, adjustment, reason, and total for invoices."""
    original = subscription_invoice_original_price(invoice)
    original_price = subscription_invoice_format_money(invoice, original)
    total = subscription_invoice_format_money(invoice, Decimal(invoice.amount))

    adjustment_type_label = ""
    adjustment_amount = ""
    adjustment_reason = ""
    if invoice.adjustment_type and invoice.adjustment_type != TenantSubscriptionInvoice.ADJUSTMENT_NONE:
        if invoice.adjustment_type == TenantSubscriptionInvoice.ADJUSTMENT_ADDITION:
            adjustment_type_label = "Addition"
            sign = "+"
        else:
            adjustment_type_label = "Deduction"
            sign = "-"
        adjustment_amount = f"{sign}{subscription_invoice_format_money(invoice, Decimal(invoice.adjustment_amount or 0))}"
        adjustment_reason = (invoice.adjustment_reason or "").strip()

    return {
        "original_price": original_price,
        "adjustment_type_label": adjustment_type_label,
        "adjustment_amount": adjustment_amount,
        "adjustment_reason": adjustment_reason,
        "total": total,
    }


def subscription_invoice_period_label(invoice: TenantSubscriptionInvoice) -> str:
    def fmt_dt(dt):
        if dt is None:
            return None
        return timezone.localtime(dt).strftime("%d %b %Y")

    start = fmt_dt(invoice.period_start)
    end = fmt_dt(invoice.period_end)
    if start and end:
        return f"{start} – {end}"
    if start:
        return f"One-time payment · {start}"
    return "—"


def is_one_time_subscription_invoice(invoice: TenantSubscriptionInvoice) -> bool:
    return invoice.period_end is None and invoice.period_start is not None


def is_package_payment(invoice: TenantSubscriptionInvoice) -> bool:
    return invoice.payment_type == TenantSubscriptionInvoice.PAYMENT_TYPE_PACKAGE


def parse_period_datetime(value, *, end_of_day: bool = False):
    """Parse API date/datetime string into an aware datetime."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, time.max if end_of_day else time.min)
    else:
        parsed_dt = parse_datetime(str(value))
        if parsed_dt is not None:
            dt = parsed_dt
        else:
            parsed_date = parse_date(str(value))
            if parsed_date is None:
                raise ValueError("Invalid period date format.")
            dt = datetime.combine(parsed_date, time.max if end_of_day else time.min)
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


def validate_charge_metadata(
    *,
    payment_type: str,
    custom_label: str = "",
    base_amount: Decimal | None = None,
    adjustment_type: str = TenantSubscriptionInvoice.ADJUSTMENT_NONE,
    adjustment_amount: Decimal | None = None,
    adjustment_reason: str = "",
    period_start=None,
    period_end=None,
    require_period: bool = True,
) -> None:
    valid_types = {choice[0] for choice in TenantSubscriptionInvoice.PAYMENT_TYPE_CHOICES}
    if payment_type not in valid_types:
        raise ValueError("payment_type must be 'package', 'setup_fee', or 'other'.")

    if payment_type == TenantSubscriptionInvoice.PAYMENT_TYPE_OTHER and not custom_label.strip():
        raise ValueError("custom_label is required when payment_type is 'other'.")

    if payment_type in (
        TenantSubscriptionInvoice.PAYMENT_TYPE_SETUP_FEE,
        TenantSubscriptionInvoice.PAYMENT_TYPE_OTHER,
    ):
        if base_amount is None or Decimal(base_amount) < 0:
            raise ValueError("base_amount is required for setup_fee and other payment types.")

    valid_adjustments = {choice[0] for choice in TenantSubscriptionInvoice.ADJUSTMENT_TYPE_CHOICES}
    if adjustment_type not in valid_adjustments:
        raise ValueError("Invalid adjustment_type.")

    adj_amt = Decimal(adjustment_amount or 0)
    if adjustment_type != TenantSubscriptionInvoice.ADJUSTMENT_NONE:
        if adj_amt <= 0:
            raise ValueError("adjustment_amount must be greater than zero when adjustment is applied.")
        if not adjustment_reason.strip():
            raise ValueError("adjustment_reason is required when adjustment is applied.")

    if payment_type == TenantSubscriptionInvoice.PAYMENT_TYPE_PACKAGE:
        if period_start is None or period_end is None:
            raise ValueError("period_start and period_end are required for package payments.")
    else:
        if require_period and period_start is None:
            raise ValueError("payment_date is required for one-time payments.")
        if period_end is not None:
            raise ValueError("period_end is not used for one-time payments.")

    if period_start is not None and period_end is not None and period_end < period_start:
        raise ValueError("period_end must be on or after period_start.")


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
    """Activate tenant plan from a successful package subscription invoice."""
    if not is_package_payment(invoice):
        return

    tenant = invoice.tenant
    if tenant is None:
        return

    tenant.is_trial = False
    tenant.status = "active"
    tenant.plan = invoice.package_slug
    tenant.subscription_start = invoice.period_start or timezone.now()
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


def maybe_activate_tenant_subscription(invoice: TenantSubscriptionInvoice) -> None:
    if invoice.status == TenantSubscriptionInvoice.STATUS_SUCCESS and is_package_payment(invoice):
        activate_tenant_subscription(invoice)


def _package_base_amount(pkg: PlatformPackage, billing_cycle: str, target_currency: str) -> Decimal:
    if billing_cycle == "yearly":
        amount_usd = pkg.price_yearly
    else:
        amount_usd = pkg.price_monthly
    return convert_currency(amount_usd, "USD", target_currency)


def create_platform_subscription_charge(
    *,
    tenant,
    package_slug: str,
    payment_type: str = TenantSubscriptionInvoice.PAYMENT_TYPE_PACKAGE,
    custom_label: str = "",
    billing_cycle: str = "monthly",
    base_amount: Decimal | None = None,
    adjustment_type: str = TenantSubscriptionInvoice.ADJUSTMENT_NONE,
    adjustment_amount: Decimal | None = None,
    adjustment_reason: str = "",
    amount_override: Decimal | None = None,
    reference_note: str,
    actor,
    period_start=None,
    period_end=None,
    notify_channels: list[str] | None = None,
) -> TenantSubscriptionInvoice:
    """Record a manual platform subscription charge as success immediately."""
    public_schema = get_public_schema_name()
    with schema_context(public_schema):
        from apps.tenancy.models import Tenant as PublicTenant

        with transaction.atomic():
            live_tenant = PublicTenant.objects.select_for_update().get(pk=tenant.pk)
            pkg = PlatformPackage.objects.filter(slug=package_slug, is_active=True).first()
            if pkg is None:
                raise ValueError(f"Package '{package_slug}' is not available.")

            ps = PlatformSettings.objects.filter(pk=1).first()
            target_currency = ps.default_currency if ps else "USD"

            if payment_type == TenantSubscriptionInvoice.PAYMENT_TYPE_PACKAGE:
                resolved_base = base_amount if base_amount is not None else _package_base_amount(
                    pkg, billing_cycle, target_currency
                )
            else:
                resolved_base = Decimal(base_amount or 0)

            validate_charge_metadata(
                payment_type=payment_type,
                custom_label=custom_label,
                base_amount=resolved_base,
                adjustment_type=adjustment_type,
                adjustment_amount=adjustment_amount,
                adjustment_reason=adjustment_reason,
                period_start=period_start,
                period_end=period_end,
                require_period=True,
            )

            final_amount = (
                amount_override
                if amount_override is not None
                else compute_final_amount(resolved_base, adjustment_type, adjustment_amount)
            )

            now = timezone.now()
            tran_id = f"MAN-{live_tenant.schema_name.upper()}-{uuid.uuid4().hex[:12].upper()}"
            invoice = TenantSubscriptionInvoice.objects.create(
                tenant=live_tenant,
                package_slug=pkg.slug,
                package_name=pkg.name,
                amount=final_amount,
                currency=target_currency,
                tran_id=tran_id,
                gateway_slug="manual",
                status=TenantSubscriptionInvoice.STATUS_SUCCESS,
                billing_cycle=billing_cycle,
                payment_type=payment_type,
                custom_label=custom_label.strip(),
                base_amount=resolved_base,
                adjustment_type=adjustment_type,
                adjustment_amount=Decimal(adjustment_amount or 0),
                adjustment_reason=adjustment_reason.strip(),
                period_start=period_start,
                period_end=period_end,
                is_trial=False,
                validated_at=now,
                gateway_response={
                    "reference_note": reference_note,
                    "created_by": getattr(actor, "pk", None),
                    "notify_channels": list(notify_channels or []),
                },
            )
            maybe_activate_tenant_subscription(invoice)
            return invoice


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
    **kwargs,
) -> TenantSubscriptionInvoice:
    """Backward-compatible wrapper for legacy package manual subscriptions."""
    return create_platform_subscription_charge(
        tenant=tenant,
        package_slug=package_slug,
        payment_type=kwargs.get("payment_type", TenantSubscriptionInvoice.PAYMENT_TYPE_PACKAGE),
        custom_label=kwargs.get("custom_label", ""),
        billing_cycle=billing_cycle,
        base_amount=kwargs.get("base_amount"),
        adjustment_type=kwargs.get(
            "adjustment_type", TenantSubscriptionInvoice.ADJUSTMENT_NONE
        ),
        adjustment_amount=kwargs.get("adjustment_amount"),
        adjustment_reason=kwargs.get("adjustment_reason", ""),
        amount_override=amount_override,
        reference_note=reference_note,
        actor=actor,
        period_start=period_start,
        period_end=period_end,
        notify_channels=notify_channels,
    )


def initiate_for_tenant(
    *,
    tenant,
    package_slug: str,
    billing_cycle: str,
    request,
    notify_channels: list[str] | None = None,
    initiated_by_platform: bool = False,
    payment_type: str = TenantSubscriptionInvoice.PAYMENT_TYPE_PACKAGE,
    adjustment_type: str = TenantSubscriptionInvoice.ADJUSTMENT_NONE,
    adjustment_amount: Decimal | None = None,
    adjustment_reason: str = "",
) -> tuple[str, str, TenantSubscriptionInvoice]:
    """Create pending invoice and initiate gateway. Returns (gateway_url, tran_id, invoice)."""
    if payment_type != TenantSubscriptionInvoice.PAYMENT_TYPE_PACKAGE:
        raise ValueError("Gateway payments are only supported for package payment type.")

    public_schema = get_public_schema_name()
    with schema_context(public_schema):
        from apps.tenancy.models import Tenant as PublicTenant

        live_tenant = PublicTenant.objects.get(pk=tenant.pk)
        pkg = PlatformPackage.objects.filter(slug=package_slug, is_active=True).first()
        if pkg is None:
            raise ValueError(f"Package '{package_slug}' is not available.")

        if billing_cycle == "yearly":
            period_days = 365
        else:
            period_days = 30

        ps = PlatformSettings.objects.filter(pk=1).first()
        target_currency = ps.default_currency if ps else "USD"
        base_amount = _package_base_amount(pkg, billing_cycle, target_currency)

        validate_charge_metadata(
            payment_type=payment_type,
            base_amount=base_amount,
            adjustment_type=adjustment_type,
            adjustment_amount=adjustment_amount,
            adjustment_reason=adjustment_reason,
            require_period=False,
        )
        amount = compute_final_amount(base_amount, adjustment_type, adjustment_amount)
        if amount <= Decimal("0"):
            raise ValueError("Free plans cannot be processed as a payment.")

        gateway = PaymentGateway.objects.filter(is_default_for_subscriptions=True).first()
        if gateway is None or not (gateway.platform_credentials or {}):
            raise RuntimeError("No subscription payment gateway is configured.")

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
            payment_type=payment_type,
            base_amount=base_amount,
            adjustment_type=adjustment_type,
            adjustment_amount=Decimal(adjustment_amount or 0),
            adjustment_reason=adjustment_reason.strip(),
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


def recalc_tenant_subscription(tenant) -> None:
    """Recalculate tenant subscription from the latest success package invoice."""
    public_schema = get_public_schema_name()
    with schema_context(public_schema):
        from apps.tenancy.models import Tenant as PublicTenant

        with transaction.atomic():
            live = PublicTenant.objects.select_for_update().get(pk=tenant.pk)
            latest = (
                TenantSubscriptionInvoice.objects.filter(
                    tenant=live,
                    status=TenantSubscriptionInvoice.STATUS_SUCCESS,
                    payment_type=TenantSubscriptionInvoice.PAYMENT_TYPE_PACKAGE,
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
