"""Platform Admin overview — the landing dashboard for public-schema users.

`TenantAdminOverviewAPIView` returns six counters that back the stat tiles on the
Tenants page. This view is the wider picture the platform team actually opens
first: growth, subscription revenue, plan mix and what changed recently.

Everything is read from the public schema in a single request and cached
briefly, because counting tenant admins walks every tenant schema.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Count, Sum
from django.utils import timezone
from django_tenants.utils import get_public_schema_name, schema_context
from rest_framework.response import Response
from rest_framework.views import APIView

from utils.cache_helpers import get_cached_value, platform_overview_key
from .constants import PLATFORM_MODULE_OVERVIEW
from .models import (
    Invitation,
    PlatformGymProfile,
    PlatformPackage,
    PlatformSettings,
    PlatformUserRole,
    Tenant,
    TenantSubscriptionInvoice,
)
from .permissions import IsPlatformFeaturePermission

User = get_user_model()

PLATFORM_OVERVIEW_TTL = 120

#: How far ahead to look when warning about trials about to lapse.
TRIAL_WARNING_DAYS = 14

#: Months of history in the revenue sparkline.
REVENUE_SERIES_MONTHS = 6


def _month_start(moment):
    return moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _percent_change(current, previous) -> float:
    """Growth from `previous` to `current`, rounded to one decimal.

    A jump from nothing is reported as 100% rather than infinity, which is what
    a reader expects from "new this month" style figures.
    """
    current = Decimal(current or 0)
    previous = Decimal(previous or 0)

    if previous == 0:
        return 100.0 if current > 0 else 0.0

    return round(float((current - previous) / previous * 100), 1)


def _count_tenant_admin_users(tenants) -> int:
    from django.db.utils import DatabaseError

    public_schema = get_public_schema_name()
    count = 0
    for tenant in tenants:
        if tenant.schema_name == public_schema:
            continue
        try:
            with schema_context(tenant.schema_name):
                count += User.objects.filter(role__in=["admin", "superuser"]).count()
        except DatabaseError:
            # A half-provisioned schema should not take the whole page down.
            continue
    return count


def _dominant_currency(default_currency: str) -> str:
    """The currency most subscription invoices are denominated in.

    Revenue figures below are restricted to a single currency — summing mixed
    currencies would produce a number that means nothing. The platform default
    is the tie-breaker when there is no billing history yet.
    """
    row = (
        TenantSubscriptionInvoice.objects.values("currency")
        .annotate(count=Count("id"))
        .order_by("-count")
        .first()
    )
    return (row or {}).get("currency") or default_currency


def _revenue_between(currency: str, start, end) -> Decimal:
    total = TenantSubscriptionInvoice.objects.filter(
        status=TenantSubscriptionInvoice.STATUS_SUCCESS,
        currency=currency,
        created_at__gte=start,
        created_at__lt=end,
    ).aggregate(total=Sum("amount"))["total"]
    return total or Decimal("0")


def _build_overview() -> dict:
    now = timezone.now()
    this_month = _month_start(now)
    last_month = _month_start(this_month - timedelta(days=1))
    public_schema = get_public_schema_name()

    with schema_context(public_schema):
        tenants = list(
            Tenant.objects.exclude(schema_name=public_schema).only(
                "id", "name", "slug", "plan", "status", "is_enabled",
                "is_trial", "trial_ends_at", "created_at", "schema_name",
            )
        )

        total = len(tenants)
        active = sum(1 for t in tenants if t.is_enabled)
        suspended = sum(1 for t in tenants if t.status == "suspended")
        trial = sum(1 for t in tenants if t.status == "trial")
        new_this_month = sum(1 for t in tenants if t.created_at and t.created_at >= this_month)
        new_last_month = sum(
            1 for t in tenants if t.created_at and last_month <= t.created_at < this_month
        )

        settings_row = PlatformSettings.objects.filter(pk=1).first()
        default_currency = (settings_row.default_currency if settings_row else "USD") or "USD"
        currency = _dominant_currency(default_currency)

        packages = {p.slug: p for p in PlatformPackage.objects.all()}

        # Monthly recurring revenue: what the currently-billable tenants are
        # worth per month at list price. Trials contribute nothing.
        mrr = Decimal("0")
        plan_counts: dict[str, int] = {}
        for tenant in tenants:
            plan_counts[tenant.plan] = plan_counts.get(tenant.plan, 0) + 1
            if not tenant.is_enabled or tenant.status == "trial":
                continue
            package = packages.get(tenant.plan)
            if package:
                mrr += package.price_monthly or Decimal("0")

        plan_distribution = sorted(
            (
                {
                    "slug": slug,
                    "name": packages[slug].name if slug in packages else slug.title(),
                    "tenants": count,
                    "price_monthly": str(
                        packages[slug].price_monthly if slug in packages else Decimal("0")
                    ),
                }
                for slug, count in plan_counts.items()
            ),
            key=lambda entry: entry["tenants"],
            reverse=True,
        )

        collected_this_month = _revenue_between(currency, this_month, now + timedelta(seconds=1))
        collected_last_month = _revenue_between(currency, last_month, this_month)

        failed_this_month = TenantSubscriptionInvoice.objects.filter(
            status=TenantSubscriptionInvoice.STATUS_FAILED,
            created_at__gte=this_month,
        ).count()
        pending_invoices = TenantSubscriptionInvoice.objects.filter(
            status=TenantSubscriptionInvoice.STATUS_PENDING,
        ).count()

        # Revenue sparkline, oldest bucket first.
        revenue_series = []
        cursor = this_month
        for _ in range(REVENUE_SERIES_MONTHS):
            bucket_start = cursor
            bucket_end = _month_start(bucket_start + timedelta(days=32))
            revenue_series.append(
                {
                    "label": bucket_start.strftime("%b"),
                    "value": str(_revenue_between(currency, bucket_start, bucket_end)),
                }
            )
            cursor = _month_start(bucket_start - timedelta(days=1))
        revenue_series.reverse()

        recent_tenants = [
            {
                "id": t.id,
                "name": t.name,
                "slug": t.slug,
                "plan": t.plan,
                "status": t.status,
                "is_enabled": t.is_enabled,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in sorted(
                (t for t in tenants if t.created_at),
                key=lambda t: t.created_at,
                reverse=True,
            )[:5]
        ]

        recent_invoices = [
            {
                "id": inv.id,
                "tenant_name": inv.tenant.name if inv.tenant_id else "",
                "package_name": inv.package_name or inv.package_slug,
                "amount": str(inv.amount),
                "currency": inv.currency,
                "status": inv.status,
                "created_at": inv.created_at.isoformat() if inv.created_at else None,
            }
            for inv in TenantSubscriptionInvoice.objects.select_related("tenant").order_by(
                "-created_at"
            )[:5]
        ]

        trial_cutoff = now + timedelta(days=TRIAL_WARNING_DAYS)
        expiring_trials = [
            {
                "id": t.id,
                "name": t.name,
                "trial_ends_at": t.trial_ends_at.isoformat(),
                "days_left": max((t.trial_ends_at - now).days, 0),
            }
            for t in sorted(
                (
                    t
                    for t in tenants
                    if t.trial_ends_at and now <= t.trial_ends_at <= trial_cutoff
                ),
                key=lambda t: t.trial_ends_at,
            )[:5]
        ]

        pending_invitations = Invitation.objects.filter(
            token_type=Invitation.TOKEN_TYPE_INVITATION,
            used_at__isnull=True,
        ).count()
        platform_team = PlatformUserRole.objects.values("user_id").distinct().count()
        profile = PlatformGymProfile.objects.filter(pk=1).first()
        tenant_admin_accounts = _count_tenant_admin_users(tenants)

    return {
        "platform_name": (profile.gym_name if profile else "") or "",
        "generated_at": now.isoformat(),
        "tenants": {
            "total": total,
            "active": active,
            "suspended": suspended,
            "trial": trial,
            "inactive": total - active,
            "new_this_month": new_this_month,
            "new_last_month": new_last_month,
            "growth_pct": _percent_change(new_this_month, new_last_month),
        },
        "accounts": {
            "tenant_admin_accounts": tenant_admin_accounts,
            "platform_team": platform_team,
            "pending_invitations": pending_invitations,
        },
        "revenue": {
            "currency": currency,
            "mrr": str(mrr),
            "collected_this_month": str(collected_this_month),
            "collected_last_month": str(collected_last_month),
            "growth_pct": _percent_change(collected_this_month, collected_last_month),
            "failed_this_month": failed_this_month,
            "pending_invoices": pending_invoices,
            "series": revenue_series,
        },
        "plan_distribution": plan_distribution,
        "recent_tenants": recent_tenants,
        "recent_invoices": recent_invoices,
        "expiring_trials": expiring_trials,
    }


class PlatformOverviewAPIView(APIView):
    """GET /api/v1/tenants/admin/platform-overview/ — platform landing stats."""

    permission_classes = [
        IsPlatformFeaturePermission.require(PLATFORM_MODULE_OVERVIEW, "view"),
    ]

    def get(self, request):
        payload = get_cached_value(
            platform_overview_key(),
            PLATFORM_OVERVIEW_TTL,
            _build_overview,
        )
        return Response(payload)
