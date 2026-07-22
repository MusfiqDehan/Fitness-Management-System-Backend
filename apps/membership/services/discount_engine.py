"""Flexible discount engine for member packages."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable, Sequence

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.billing.services.line_items import normalize_line_items
from apps.billing.services.package_add_ons import normalize_package_add_ons

TWOPLACES = Decimal("0.01")


def _d(value: Any) -> Decimal:
    try:
        return Decimal(str(value)).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal("0.00")


def _money(value: Decimal) -> Decimal:
    return max(value, Decimal("0.00")).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


@dataclass
class CartContext:
    package_id: int | None
    package_price: Decimal
    package_duration_days: int = 30
    package_name: str = "Package"
    addon_lines: list[dict[str, Any]] = field(default_factory=list)
    coverage_qty: int = 1
    member_id: int | None = None
    branch_id: int | None = None
    membership_type: str | None = None
    member_is_new: bool = False
    coupon_code: str | None = None
    now: datetime | None = None

    @property
    def package_subtotal(self) -> Decimal:
        qty = max(int(self.coverage_qty or 1), 1)
        return _money(self.package_price * qty)

    @property
    def addon_subtotal(self) -> Decimal:
        return _money(sum((_d(a.get("amount", 0)) for a in self.addon_lines), Decimal("0")))

    @property
    def charge_subtotal(self) -> Decimal:
        return _money(self.package_subtotal + self.addon_subtotal)


@dataclass
class AppliedDiscount:
    discount_id: int | None
    name: str
    amount_saved: Decimal
    coupon_code: str = ""
    meta: dict[str, Any] = field(default_factory=dict)
    extra_duration_days: int = 0
    free_addon_names: list[str] = field(default_factory=list)


@dataclass
class ApplyResult:
    charge_line_items: list[dict[str, Any]]
    discount_line_items: list[dict[str, Any]]
    line_items: list[dict[str, Any]]
    total: Decimal
    amount_saved: Decimal
    applied: list[AppliedDiscount]
    extra_duration_days: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "original_total": str(_money(self.total + self.amount_saved)),
            "amount_saved": str(self.amount_saved),
            "final_total": str(self.total),
            "line_items": self.line_items,
            "extra_duration_days": self.extra_duration_days,
            "applied": [
                {
                    "discount_id": a.discount_id,
                    "name": a.name,
                    "amount_saved": str(a.amount_saved),
                    "coupon_code": a.coupon_code,
                    "meta": a.meta,
                    "extra_duration_days": a.extra_duration_days,
                    "free_addon_names": a.free_addon_names,
                }
                for a in self.applied
            ],
        }


def build_charge_line_items(ctx: CartContext) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if ctx.package_id is not None:
        items.append(
            {
                "type": "package",
                "name": ctx.package_name,
                "amount": f"{ctx.package_subtotal:.2f}",
                "ref": str(ctx.package_id),
            }
        )
    for addon in ctx.addon_lines:
        items.append(
            {
                "type": "addon",
                "name": str(addon.get("name") or "Add-on"),
                "amount": f"{_d(addon.get('amount', 0)):.2f}",
            }
        )
    return normalize_line_items(items)


def evaluate_condition(condition: Any, ctx: CartContext) -> bool:
    field_name = str(getattr(condition, "field", "") or "").strip()
    operator = str(getattr(condition, "operator", "eq") or "eq").strip().lower()
    raw_value = getattr(condition, "value", None)
    if isinstance(raw_value, dict) and "value" in raw_value and len(raw_value) == 1:
        expected = raw_value["value"]
    else:
        expected = raw_value

    actual_map = {
        "branch_id": ctx.branch_id,
        "membership_type": ctx.membership_type,
        "member_is_new": ctx.member_is_new,
        "min_cart_amount": ctx.charge_subtotal,
        "cart_amount": ctx.charge_subtotal,
        "coverage_qty": ctx.coverage_qty,
        "day_of_week": (ctx.now or timezone.now()).weekday(),
        "package_id": ctx.package_id,
    }
    actual = actual_map.get(field_name)
    if field_name == "min_cart_amount":
        # Treat as gte against cart when operator defaults to eq with a number.
        try:
            return ctx.charge_subtotal >= _d(expected)
        except Exception:
            return False

    if operator == "eq":
        return actual == expected or str(actual) == str(expected)
    if operator == "neq":
        return actual != expected and str(actual) != str(expected)
    if operator == "in":
        values = expected if isinstance(expected, (list, tuple, set)) else [expected]
        return actual in values or str(actual) in {str(v) for v in values}
    if operator == "gte":
        return _d(actual) >= _d(expected)
    if operator == "lte":
        return _d(actual) <= _d(expected)
    if operator == "between":
        if not isinstance(expected, (list, tuple)) or len(expected) != 2:
            return False
        return _d(expected[0]) <= _d(actual) <= _d(expected[1])
    return False


def conditions_pass(discount: Any, ctx: CartContext) -> bool:
    conditions = list(getattr(discount, "prefetched_conditions", None) or [])
    if not conditions and hasattr(discount, "conditions"):
        try:
            conditions = list(discount.conditions.filter(is_deleted=False))
        except Exception:
            conditions = list(getattr(discount, "conditions", []) or [])
    if not conditions:
        return True
    logic = str(getattr(discount, "condition_logic", "and") or "and").lower()
    results = [evaluate_condition(c, ctx) for c in conditions]
    if logic == "or":
        return any(results)
    return all(results)


def in_schedule(discount: Any, now: datetime) -> bool:
    starts = getattr(discount, "starts_at", None)
    ends = getattr(discount, "ends_at", None)
    if starts and now < starts:
        return False
    if ends and now > ends:
        return False
    return True


def in_scope(discount: Any, package_id: int | None) -> bool:
    scope = getattr(discount, "scope", None) or {}
    if not isinstance(scope, dict):
        return True
    package_ids = scope.get("package_ids")
    if package_ids is None or package_ids == [] or package_ids == "all":
        return True
    if package_id is None:
        return False
    try:
        ids = {int(x) for x in package_ids}
    except (TypeError, ValueError):
        return False
    return int(package_id) in ids


def matches_application_mode(discount: Any, coupon_code: str | None) -> bool:
    mode = str(getattr(discount, "application_mode", "automatic") or "automatic")
    code = (coupon_code or "").strip().upper()
    discount_code = (getattr(discount, "coupon_code", None) or "").strip().upper()
    if mode == "automatic":
        return True
    if mode == "coupon":
        return bool(code) and code == discount_code
    if mode == "both":
        if not discount_code:
            return True
        return (not code) or code == discount_code
    return False


def compute_type_savings(discount: Any, ctx: CartContext, package_remaining: Decimal) -> AppliedDiscount:
    dtype = str(getattr(discount, "discount_type", "") or "")
    config = getattr(discount, "config", None) or {}
    name = str(getattr(discount, "name", "Discount") or "Discount")
    discount_id = getattr(discount, "id", None)
    coupon = (getattr(discount, "coupon_code", None) or "").strip().upper()
    applied = AppliedDiscount(
        discount_id=discount_id,
        name=name,
        amount_saved=Decimal("0.00"),
        coupon_code=coupon if (ctx.coupon_code or "").strip().upper() == coupon else "",
    )

    if dtype == "percentage":
        percent = _d(config.get("percent", 0))
        saved = _money(package_remaining * percent / Decimal("100"))
        max_discount = config.get("max_discount")
        if max_discount is not None:
            saved = min(saved, _d(max_discount))
        applied.amount_saved = min(saved, package_remaining)
        applied.meta = {"percent": str(percent)}
        return applied

    if dtype == "fixed_amount":
        saved = min(_d(config.get("amount", 0)), package_remaining)
        applied.amount_saved = _money(saved)
        return applied

    if dtype == "fixed_price":
        target = _d(config.get("price", package_remaining))
        # Apply against single-unit package price * qty remaining proportionally.
        saved = _money(package_remaining - min(target * max(ctx.coverage_qty, 1), package_remaining))
        # If fixed price is absolute cart package price for full coverage:
        if config.get("per_unit"):
            unit_target = _d(config.get("price", 0))
            target_total = unit_target * max(ctx.coverage_qty, 1)
            saved = _money(package_remaining - min(target_total, package_remaining))
        else:
            saved = _money(max(package_remaining - target, Decimal("0")))
        applied.amount_saved = saved
        applied.meta = {"fixed_price": str(target)}
        return applied

    if dtype == "buy_x_get_y":
        buy_qty = int(config.get("buy_qty") or 0)
        get_qty = int(config.get("get_qty") or 0)
        get_target = str(config.get("get_target") or "duration")
        if buy_qty > 0 and get_qty > 0 and ctx.coverage_qty >= buy_qty:
            if get_target == "duration":
                applied.extra_duration_days = get_qty * max(int(ctx.package_duration_days or 0), 0)
                applied.meta = {
                    "buy_qty": buy_qty,
                    "get_qty": get_qty,
                    "get_target": get_target,
                }
            else:
                unit = ctx.package_price
                saved = _money(unit * get_qty)
                applied.amount_saved = min(saved, package_remaining)
                applied.meta = {"buy_qty": buy_qty, "get_qty": get_qty}
        return applied

    if dtype == "tiered":
        tiers = config.get("tiers") or []
        best_percent = Decimal("0")
        matched = None
        for tier in sorted(tiers, key=lambda t: int((t or {}).get("min_qty") or 0)):
            min_qty = int((tier or {}).get("min_qty") or 0)
            if ctx.coverage_qty >= min_qty:
                best_percent = _d((tier or {}).get("percent", 0))
                matched = tier
        saved = _money(package_remaining * best_percent / Decimal("100"))
        applied.amount_saved = min(saved, package_remaining)
        applied.meta = {"tier": matched, "percent": str(best_percent)}
        return applied

    if dtype == "free_addon":
        names = [str(n).strip().lower() for n in (config.get("addon_names") or []) if str(n).strip()]
        indexes = config.get("addon_indexes") or []
        free_names: list[str] = []
        saved = Decimal("0.00")
        for idx, addon in enumerate(ctx.addon_lines):
            addon_name = str(addon.get("name") or "")
            match = False
            if names and addon_name.strip().lower() in names:
                match = True
            if indexes and idx in indexes:
                match = True
            if match:
                free_names.append(addon_name)
                saved += _d(addon.get("amount", 0))
        applied.amount_saved = _money(saved)
        applied.free_addon_names = free_names
        applied.meta = {"free_addon_names": free_names}
        return applied

    return applied


def select_stackable(discounts: Sequence[Any]) -> list[Any]:
    """Sort by priority ascending; one exclusive then compatible stackables."""
    ordered = sorted(
        discounts,
        key=lambda d: (int(getattr(d, "priority", 100) or 100), getattr(d, "id", 0) or 0),
    )
    non_stack = [d for d in ordered if not bool(getattr(d, "is_stackable", False))]
    stack = [d for d in ordered if bool(getattr(d, "is_stackable", False))]
    selected: list[Any] = []
    used_groups: set[str] = set()

    def _add(d: Any) -> None:
        group = str(getattr(d, "stack_group", "") or "").strip()
        if group and group in used_groups:
            return
        selected.append(d)
        if group:
            used_groups.add(group)

    if non_stack:
        _add(non_stack[0])
        for d in stack:
            _add(d)
    else:
        for d in stack:
            _add(d)
    return selected


def resolve_and_apply(
    discounts: Iterable[Any],
    ctx: CartContext,
    *,
    usage_counts: dict[int, int] | None = None,
    member_usage_counts: dict[int, int] | None = None,
    require_coupon_if_provided: bool = True,
) -> ApplyResult:
    now = ctx.now or timezone.now()
    usage_counts = usage_counts or {}
    member_usage_counts = member_usage_counts or {}
    coupon = (ctx.coupon_code or "").strip().upper()

    eligible: list[Any] = []
    coupon_matched = False
    for d in discounts:
        if not getattr(d, "is_active", True) or getattr(d, "is_deleted", False):
            continue
        if not in_schedule(d, now):
            continue
        if not in_scope(d, ctx.package_id):
            continue
        if not conditions_pass(d, ctx):
            continue
        if not matches_application_mode(d, coupon or None):
            continue
        did = getattr(d, "id", None)
        limit_total = getattr(d, "usage_limit_total", None)
        if did is not None and limit_total is not None and usage_counts.get(did, 0) >= int(limit_total):
            continue
        limit_member = getattr(d, "usage_limit_per_member", None)
        if (
            did is not None
            and limit_member is not None
            and ctx.member_id is not None
            and member_usage_counts.get(did, 0) >= int(limit_member)
        ):
            continue
        mode = str(getattr(d, "application_mode", "") or "")
        dcode = (getattr(d, "coupon_code", None) or "").strip().upper()
        if coupon and dcode == coupon and mode in ("coupon", "both"):
            coupon_matched = True
        # Automatic-only discounts always considered; coupon-mode only when code matches (already filtered)
        if mode == "automatic" or mode == "both":
            if mode == "both" and dcode and coupon and dcode != coupon:
                continue
            eligible.append(d)
        elif mode == "coupon" and coupon and dcode == coupon:
            eligible.append(d)

    if coupon and require_coupon_if_provided and not coupon_matched:
        # Allow if some automatic still applies? Spec: invalid coupon errors.
        raise ValidationError({"coupon_code": "Invalid or ineligible coupon code."})

    selected = select_stackable(eligible)
    charge_items = build_charge_line_items(ctx)
    package_remaining = ctx.package_subtotal
    addon_remaining_by_name = {
        str(a.get("name") or ""): _d(a.get("amount", 0)) for a in ctx.addon_lines
    }
    applied: list[AppliedDiscount] = []
    discount_items: list[dict[str, Any]] = []
    extra_days = 0

    for d in selected:
        result = compute_type_savings(d, ctx, package_remaining)
        dtype = str(getattr(d, "discount_type", "") or "")
        if dtype == "free_addon":
            # Cap free-addon savings to remaining addon amounts
            capped = Decimal("0.00")
            for n in result.free_addon_names:
                capped += addon_remaining_by_name.get(n, Decimal("0.00"))
                addon_remaining_by_name[n] = Decimal("0.00")
            result.amount_saved = _money(min(result.amount_saved, capped))
        else:
            result.amount_saved = _money(min(result.amount_saved, package_remaining))
            package_remaining = _money(package_remaining - result.amount_saved)

        if result.amount_saved > 0 or result.extra_duration_days > 0:
            applied.append(result)
            extra_days += result.extra_duration_days
            if result.amount_saved > 0:
                discount_items.append(
                    {
                        "type": "discount",
                        "name": result.name,
                        "amount": f"{result.amount_saved:.2f}",
                        "ref": str(result.discount_id) if result.discount_id is not None else "",
                    }
                )

    discount_items = normalize_line_items(discount_items)
    amount_saved = _money(sum((_d(i["amount"]) for i in discount_items), Decimal("0")))
    # free duration-only discounts don't change amount_saved from items
    for a in applied:
        if a.amount_saved and all(i.get("name") != a.name for i in discount_items):
            amount_saved = _money(amount_saved + a.amount_saved)

    total = _money(ctx.charge_subtotal - amount_saved)
    line_items = charge_items + discount_items
    return ApplyResult(
        charge_line_items=charge_items,
        discount_line_items=discount_items,
        line_items=line_items,
        total=total,
        amount_saved=amount_saved,
        applied=applied,
        extra_duration_days=extra_days,
    )


def load_usage_counts(discount_ids: Sequence[int], member_id: int | None) -> tuple[dict[int, int], dict[int, int]]:
    from apps.membership.models import DiscountUsage

    if not discount_ids:
        return {}, {}
    totals = {
        row["discount_id"]: row["c"]
        for row in DiscountUsage.objects.filter(discount_id__in=discount_ids)
        .values("discount_id")
        .annotate(c=Count("id"))
    }
    member_totals: dict[int, int] = {}
    if member_id is not None:
        member_totals = {
            row["discount_id"]: row["c"]
            for row in DiscountUsage.objects.filter(
                discount_id__in=discount_ids, member_id=member_id
            )
            .values("discount_id")
            .annotate(c=Count("id"))
        }
    return totals, member_totals


def get_active_discounts_queryset():
    from django.utils import timezone as dj_tz

    from apps.membership.models import Discount

    expire_ended_discounts()
    now = dj_tz.now()
    return (
        Discount.objects.filter(is_deleted=False, is_active=True)
        .filter(Q(starts_at__isnull=True) | Q(starts_at__lte=now))
        .filter(Q(ends_at__isnull=True) | Q(ends_at__gte=now))
        .prefetch_related("conditions")
        .order_by("priority", "id")
    )


def expire_ended_discounts() -> int:
    """Auto-disable discounts whose ends_at has passed. Returns rows updated."""
    from django.utils import timezone as dj_tz

    from apps.membership.models import Discount

    now = dj_tz.now()
    return Discount.objects.filter(
        is_deleted=False,
        is_active=True,
        ends_at__isnull=False,
        ends_at__lt=now,
    ).update(is_active=False)


def apply_discounts_for_payment(
    *,
    package,
    member,
    coverage_months: list[str] | None,
    selected_addon_names: list[str] | None = None,
    coupon_code: str | None = None,
    existing_line_items: list[dict] | None = None,
    feature_enabled: bool = True,
) -> ApplyResult | None:
    """Build cart from package/member and apply engine. Returns None if feature off."""
    if not feature_enabled:
        return None

    addons = normalize_package_add_ons(getattr(package, "add_ons", None) or [])
    if selected_addon_names is not None:
        wanted = {n.strip().lower() for n in selected_addon_names}
        addons = [a for a in addons if a["name"].strip().lower() in wanted]
    elif existing_line_items:
        # Prefer addon lines already chosen on the payment payload
        addons = [
            {"name": i["name"], "amount": i["amount"]}
            for i in existing_line_items
            if str(i.get("type")) == "addon"
        ]

    coverage_qty = len(coverage_months) if coverage_months else 1
    ctx = CartContext(
        package_id=getattr(package, "id", None),
        package_price=_d(getattr(package, "price", 0)),
        package_duration_days=int(getattr(package, "duration_in_days", 30) or 30),
        package_name=str(getattr(package, "name", "Package") or "Package"),
        addon_lines=addons,
        coverage_qty=max(coverage_qty, 1),
        member_id=getattr(member, "id", None),
        branch_id=getattr(member, "branch_id", None),
        membership_type=getattr(member, "membership_type", None),
        member_is_new=not bool(getattr(member, "payments", None) and member.payments.exists())
        if member is not None and hasattr(member, "payments")
        else True,
        coupon_code=coupon_code,
    )

    qs = get_active_discounts_queryset()
    discounts = list(qs)
    for d in discounts:
        d.prefetched_conditions = [
            c for c in d.conditions.all() if not getattr(c, "is_deleted", False)
        ]

    ids = [d.id for d in discounts]
    usage_counts, member_usage = load_usage_counts(ids, ctx.member_id)
    return resolve_and_apply(
        discounts,
        ctx,
        usage_counts=usage_counts,
        member_usage_counts=member_usage,
        require_coupon_if_provided=bool((coupon_code or "").strip()),
    )


@transaction.atomic
def record_discount_usages(*, payment, apply_result: ApplyResult, coupon_code: str | None = None) -> None:
    from apps.membership.models import DiscountUsage

    if not apply_result.applied:
        return
    code = (coupon_code or "").strip().upper()
    for item in apply_result.applied:
        if item.discount_id is None:
            continue
        DiscountUsage.objects.get_or_create(
            payment=payment,
            discount_id=item.discount_id,
            defaults={
                "member_id": getattr(payment, "member_id", None),
                "coupon_code_used": code or item.coupon_code,
                "amount_saved": item.amount_saved,
                "meta": {
                    **(item.meta or {}),
                    "extra_duration_days": item.extra_duration_days,
                    "free_addon_names": item.free_addon_names,
                },
            },
        )


LIST_PRICE_TYPES = frozenset({"percentage", "fixed_amount", "fixed_price"})


def _is_all_packages_scope(discount: Any) -> bool:
    scope = getattr(discount, "scope", None) or {}
    if not isinstance(scope, dict):
        return True
    package_ids = scope.get("package_ids")
    return package_ids is None or package_ids == [] or package_ids == "all"


def _listing_mode_ok(discount: Any) -> bool:
    mode = str(getattr(discount, "application_mode", "") or "")
    return mode in ("automatic", "both")


def _listing_base_eligible(discount: Any, ctx: CartContext, now: datetime) -> bool:
    if not getattr(discount, "is_active", True) or getattr(discount, "is_deleted", False):
        return False
    if not _listing_mode_ok(discount):
        return False
    if not in_schedule(discount, now):
        return False
    if not in_scope(discount, ctx.package_id):
        return False
    if not conditions_pass(discount, ctx):
        return False
    return True


def _unit_final_price(discount: Any, package_price: Decimal) -> tuple[Decimal, AppliedDiscount]:
    ctx = CartContext(
        package_id=None,
        package_price=package_price,
        coverage_qty=1,
    )
    applied = compute_type_savings(discount, ctx, package_price)
    final = _money(package_price - applied.amount_saved)
    return final, applied


def resolve_list_display_for_package(
    package: Any,
    discounts: Sequence[Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """
    Compute listing display for one package.

    Returns None when neither list price nor percent badge applies.
    """
    now = now or timezone.now()
    package_id = getattr(package, "id", None)
    package_price = _d(getattr(package, "price", 0))
    ctx = CartContext(
        package_id=package_id,
        package_price=package_price,
        package_duration_days=int(getattr(package, "duration_in_days", 30) or 30),
        package_name=str(getattr(package, "name", "Package") or "Package"),
        coverage_qty=1,
        now=now,
    )

    best_price: tuple[Decimal, Any, AppliedDiscount] | None = None
    for d in discounts:
        if not getattr(d, "show_list_price", False):
            continue
        dtype = str(getattr(d, "discount_type", "") or "")
        if dtype not in LIST_PRICE_TYPES:
            continue
        if not _listing_base_eligible(d, ctx, now):
            continue
        final, applied = _unit_final_price(d, package_price)
        if final >= package_price:
            continue
        priority = int(getattr(d, "priority", 100) or 100)
        if best_price is None:
            best_price = (final, d, applied)
            continue
        prev_final, prev_d, _ = best_price
        prev_priority = int(getattr(prev_d, "priority", 100) or 100)
        if final < prev_final or (final == prev_final and priority < prev_priority):
            best_price = (final, d, applied)

    best_badge: tuple[Decimal, Any] | None = None
    for d in discounts:
        if not getattr(d, "show_percent_badge", False):
            continue
        if str(getattr(d, "discount_type", "") or "") != "percentage":
            continue
        if not _listing_base_eligible(d, ctx, now):
            continue
        percent = _d((getattr(d, "config", None) or {}).get("percent", 0))
        if percent <= 0:
            continue
        if best_badge is None or percent > best_badge[0]:
            best_badge = (percent, d)
            continue
        if percent == best_badge[0]:
            cur_p = int(getattr(d, "priority", 100) or 100)
            prev_p = int(getattr(best_badge[1], "priority", 100) or 100)
            if cur_p < prev_p:
                best_badge = (percent, d)

    if best_price is None and best_badge is None:
        return None

    result: dict[str, Any] = {
        "original_price": f"{package_price:.2f}",
        "discounted_price": None,
        "amount_saved": None,
        "percent_off": None,
        "badge_placement": "none",
        "discount_id": None,
        "discount_name": None,
    }

    if best_price is not None:
        final, d, applied = best_price
        result["discounted_price"] = f"{final:.2f}"
        result["amount_saved"] = f"{applied.amount_saved:.2f}"
        result["discount_id"] = getattr(d, "id", None)
        result["discount_name"] = str(getattr(d, "name", "") or "")
        if str(getattr(d, "discount_type", "") or "") == "percentage":
            result["percent_off"] = str(_d((getattr(d, "config", None) or {}).get("percent", 0)))

    if best_badge is not None:
        percent, d = best_badge
        if percent == percent.to_integral_value():
            result["percent_off"] = str(int(percent))
        else:
            result["percent_off"] = f"{percent:.2f}"
        result["badge_placement"] = "global" if _is_all_packages_scope(d) else "card"
        if result["discount_id"] is None:
            result["discount_id"] = getattr(d, "id", None)
            result["discount_name"] = str(getattr(d, "name", "") or "")

    return result


def load_listing_discounts() -> list[Any]:
    """Active non-deleted discounts that may affect listings."""
    from apps.membership.models import Discount

    return list(
        Discount.objects.filter(is_deleted=False, is_active=True)
        .filter(application_mode__in=["automatic", "both"])
        .filter(Q(show_list_price=True) | Q(show_percent_badge=True))
        .prefetch_related("conditions")
        .order_by("priority", "id")
    )


def build_package_list_display_map(
    packages: Sequence[Any],
    discounts: Sequence[Any] | None = None,
    *,
    now: datetime | None = None,
) -> dict[int, dict[str, Any]]:
    """Map package_id → discount_list_display dict for serializer context."""
    discounts = list(discounts) if discounts is not None else load_listing_discounts()
    now = now or timezone.now()
    out: dict[int, dict[str, Any]] = {}
    for package in packages:
        pid = getattr(package, "id", None)
        if pid is None:
            continue
        display = resolve_list_display_for_package(package, discounts, now=now)
        if display is not None:
            out[int(pid)] = display
    return out
