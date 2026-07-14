"""Unit tests for discount engine (no DB required for core math)."""
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest import TestCase

from rest_framework.exceptions import ValidationError

from apps.billing.services.line_items import normalize_line_items, total_from_line_items
from apps.membership.services.discount_engine import (
    CartContext,
    compute_type_savings,
    resolve_and_apply,
    resolve_list_display_for_package,
    select_stackable,
)


def _discount(**kwargs):
    defaults = dict(
        id=1,
        name="D",
        discount_type="percentage",
        config={"percent": 10},
        application_mode="automatic",
        coupon_code=None,
        priority=100,
        is_stackable=False,
        stack_group="",
        scope={},
        condition_logic="and",
        starts_at=None,
        ends_at=None,
        usage_limit_total=None,
        usage_limit_per_member=None,
        is_active=True,
        is_deleted=False,
        show_list_price=False,
        show_percent_badge=False,
        prefetched_conditions=[],
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class LineItemsDiscountTypeTests(TestCase):
    def test_discount_type_and_total(self):
        items = normalize_line_items(
            [
                {"type": "package", "name": "Gold", "amount": "1000"},
                {"type": "discount", "name": "SAVE", "amount": "100"},
            ]
        )
        self.assertEqual(total_from_line_items(items), Decimal("900.00"))


class DiscountTypeMathTests(TestCase):
    def setUp(self):
        self.ctx = CartContext(
            package_id=1,
            package_price=Decimal("1000.00"),
            package_duration_days=30,
            package_name="Gold",
            addon_lines=[{"name": "Locker", "amount": "200.00"}],
            coverage_qty=1,
        )

    def test_percentage(self):
        d = _discount(discount_type="percentage", config={"percent": 10})
        r = compute_type_savings(d, self.ctx, Decimal("1000.00"))
        self.assertEqual(r.amount_saved, Decimal("100.00"))

    def test_fixed_amount(self):
        d = _discount(discount_type="fixed_amount", config={"amount": 250})
        r = compute_type_savings(d, self.ctx, Decimal("1000.00"))
        self.assertEqual(r.amount_saved, Decimal("250.00"))

    def test_fixed_price(self):
        d = _discount(discount_type="fixed_price", config={"price": 799})
        r = compute_type_savings(d, self.ctx, Decimal("1000.00"))
        self.assertEqual(r.amount_saved, Decimal("201.00"))

    def test_buy_x_get_y_duration(self):
        d = _discount(
            discount_type="buy_x_get_y",
            config={"buy_qty": 2, "get_qty": 1, "get_target": "duration"},
        )
        ctx = CartContext(
            package_id=1,
            package_price=Decimal("1000.00"),
            package_duration_days=30,
            coverage_qty=2,
        )
        r = compute_type_savings(d, ctx, Decimal("2000.00"))
        self.assertEqual(r.extra_duration_days, 30)
        self.assertEqual(r.amount_saved, Decimal("0.00"))

    def test_tiered(self):
        d = _discount(
            discount_type="tiered",
            config={
                "tiers": [
                    {"min_qty": 1, "percent": 0},
                    {"min_qty": 3, "percent": 10},
                    {"min_qty": 6, "percent": 20},
                ]
            },
        )
        ctx = CartContext(package_id=1, package_price=Decimal("1000.00"), coverage_qty=3)
        r = compute_type_savings(d, ctx, Decimal("3000.00"))
        self.assertEqual(r.amount_saved, Decimal("300.00"))

    def test_free_addon(self):
        d = _discount(discount_type="free_addon", config={"addon_names": ["Locker"]})
        r = compute_type_savings(d, self.ctx, Decimal("1000.00"))
        self.assertEqual(r.amount_saved, Decimal("200.00"))
        self.assertEqual(r.free_addon_names, ["Locker"])


class StackingAndCouponTests(TestCase):
    def test_exclusive_blocks_second_non_stackable(self):
        a = _discount(id=1, priority=10, is_stackable=False, config={"percent": 10})
        b = _discount(id=2, priority=20, is_stackable=False, config={"percent": 50})
        selected = select_stackable([a, b])
        self.assertEqual([d.id for d in selected], [1])

    def test_stackable_with_exclusive(self):
        a = _discount(id=1, priority=10, is_stackable=False, config={"percent": 10})
        b = _discount(id=2, priority=20, is_stackable=True, config={"amount": 50}, discount_type="fixed_amount")
        selected = select_stackable([a, b])
        self.assertEqual([d.id for d in selected], [1, 2])

    def test_apply_percentage_auto(self):
        d = _discount(id=5, config={"percent": 10}, name="Auto10")
        ctx = CartContext(package_id=1, package_price=Decimal("1000.00"), coverage_qty=1)
        result = resolve_and_apply([d], ctx, require_coupon_if_provided=False)
        self.assertEqual(result.total, Decimal("900.00"))
        self.assertEqual(result.amount_saved, Decimal("100.00"))
        self.assertEqual(result.discount_line_items[0]["type"], "discount")

    def test_invalid_coupon_raises(self):
        d = _discount(
            application_mode="coupon",
            coupon_code="GOOD",
            config={"percent": 10},
        )
        ctx = CartContext(
            package_id=1,
            package_price=Decimal("1000.00"),
            coupon_code="BAD",
        )
        with self.assertRaises(ValidationError):
            resolve_and_apply([d], ctx, require_coupon_if_provided=True)

    def test_usage_limit_blocks(self):
        d = _discount(id=9, usage_limit_total=1, config={"percent": 10})
        ctx = CartContext(package_id=1, package_price=Decimal("1000.00"))
        result = resolve_and_apply([d], ctx, usage_counts={9: 1}, require_coupon_if_provided=False)
        self.assertEqual(result.amount_saved, Decimal("0.00"))

    def test_scope_miss(self):
        d = _discount(scope={"package_ids": [99]}, config={"percent": 10})
        ctx = CartContext(package_id=1, package_price=Decimal("1000.00"))
        result = resolve_and_apply([d], ctx, require_coupon_if_provided=False)
        self.assertEqual(result.amount_saved, Decimal("0.00"))

    def test_condition_branch(self):
        cond = SimpleNamespace(field="branch_id", operator="eq", value=5)
        d = _discount(prefetched_conditions=[cond], config={"percent": 10})
        ctx = CartContext(package_id=1, package_price=Decimal("1000.00"), branch_id=7)
        result = resolve_and_apply([d], ctx, require_coupon_if_provided=False)
        self.assertEqual(result.amount_saved, Decimal("0.00"))

    def test_schedule_future(self):
        future = datetime(2099, 1, 1, tzinfo=dt_timezone.utc)
        d = _discount(starts_at=future, config={"percent": 10})
        ctx = CartContext(
            package_id=1,
            package_price=Decimal("1000.00"),
            now=datetime(2026, 7, 14, tzinfo=dt_timezone.utc),
        )
        result = resolve_and_apply([d], ctx, require_coupon_if_provided=False)
        self.assertEqual(result.amount_saved, Decimal("0.00"))

    def test_ended_schedule_skips(self):
        past = datetime(2020, 1, 1, tzinfo=dt_timezone.utc)
        d = _discount(ends_at=past, config={"percent": 10})
        ctx = CartContext(
            package_id=1,
            package_price=Decimal("1000.00"),
            now=datetime(2026, 7, 14, tzinfo=dt_timezone.utc),
        )
        result = resolve_and_apply([d], ctx, require_coupon_if_provided=False)
        self.assertEqual(result.amount_saved, Decimal("0.00"))


class DiscountListDisplayTests(TestCase):
    def test_defaults_off_returns_none(self):
        pkg = SimpleNamespace(id=1, price=Decimal("1000.00"), duration_in_days=30, name="Gold")
        d = _discount(show_list_price=False, config={"percent": 20})
        self.assertIsNone(resolve_list_display_for_package(pkg, [d]))

    def test_best_savings_wins(self):
        pkg = SimpleNamespace(id=1, price=Decimal("1000.00"), duration_in_days=30, name="Gold")
        weak = _discount(id=1, show_list_price=True, config={"percent": 10}, priority=1)
        strong = _discount(id=2, show_list_price=True, config={"percent": 25}, priority=50)
        display = resolve_list_display_for_package(pkg, [weak, strong])
        self.assertEqual(display["discounted_price"], "750.00")
        self.assertEqual(display["discount_id"], 2)

    def test_coupon_only_ignored(self):
        pkg = SimpleNamespace(id=1, price=Decimal("1000.00"), duration_in_days=30, name="Gold")
        d = _discount(
            show_list_price=True,
            application_mode="coupon",
            coupon_code="SAVE20",
            config={"percent": 20},
        )
        self.assertIsNone(resolve_list_display_for_package(pkg, [d]))

    def test_global_percent_badge(self):
        pkg = SimpleNamespace(id=1, price=Decimal("1000.00"), duration_in_days=30, name="Gold")
        d = _discount(
            show_percent_badge=True,
            show_list_price=True,
            config={"percent": 20},
            scope={},
        )
        display = resolve_list_display_for_package(pkg, [d])
        self.assertEqual(display["badge_placement"], "global")
        self.assertEqual(display["percent_off"], "20")
        self.assertEqual(display["discounted_price"], "800.00")

    def test_card_badge_when_scoped(self):
        pkg = SimpleNamespace(id=5, price=Decimal("1000.00"), duration_in_days=30, name="Gold")
        d = _discount(
            show_percent_badge=True,
            show_list_price=False,
            config={"percent": 15},
            scope={"package_ids": [5]},
        )
        display = resolve_list_display_for_package(pkg, [d])
        self.assertEqual(display["badge_placement"], "card")
        self.assertIsNone(display["discounted_price"])
        self.assertEqual(display["percent_off"], "15")
