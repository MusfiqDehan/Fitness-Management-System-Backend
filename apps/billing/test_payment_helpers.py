"""Unit tests for payment coverage / line-item / export helpers (no DB)."""
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest import TestCase

from apps.billing.services.coverage_months import (
    format_coverage_months_label,
    month_key_from_datetime,
    normalize_coverage_months,
)
from apps.billing.services.line_items import normalize_line_items
from apps.billing.services.package_add_ons import normalize_package_add_ons
from apps.billing.services.payment_export import (
    EXPORT_HEADERS,
    EXPORT_MAX_ROWS,
    _row_from_payment,
    build_payment_export_response,
)
from rest_framework.exceptions import ValidationError


class CoverageMonthsHelperTests(TestCase):
    def test_normalize_sorts_and_uniques(self):
        self.assertEqual(
            normalize_coverage_months(["2026-09", "2026-07", "2026-09"]),
            ["2026-07", "2026-09"],
        )

    def test_normalize_defaults_from_payment_date(self):
        dt = datetime(2026, 7, 15, 10, 0, 0, tzinfo=dt_timezone.utc)
        self.assertEqual(normalize_coverage_months(None, payment_date=dt), ["2026-07"])

    def test_normalize_rejects_invalid_month(self):
        with self.assertRaises(ValidationError):
            normalize_coverage_months(["2026-13"])

    def test_format_label(self):
        self.assertEqual(
            format_coverage_months_label(["2026-07", "2026-09"]),
            "Jul 2026, Sep 2026",
        )

    def test_month_key(self):
        self.assertEqual(
            month_key_from_datetime(datetime(2026, 12, 1, tzinfo=dt_timezone.utc)),
            "2026-12",
        )


class LineItemsAndAddOnsHelperTests(TestCase):
    def test_line_items_normalize(self):
        items = normalize_line_items(
            [
                {"type": "package", "name": "Gold", "amount": "2000"},
                {"type": "addon", "name": "PT", "amount": "500"},
                {"type": "custom", "name": "Adj", "amount": "0"},
            ]
        )
        self.assertEqual(items[0]["amount"], "2000.00")
        self.assertEqual(len(items), 3)

    def test_package_add_ons_legacy_string(self):
        self.assertEqual(
            normalize_package_add_ons(["Locker"]),
            [{"name": "Locker", "amount": "0.00"}],
        )


class PaymentExportHelperTests(TestCase):
    def test_row_and_csv_total(self):
        member = SimpleNamespace(
            full_name="Alice",
            phone_number="017",
            email="a@t.com",
            member_package_id=1,
            member_package=SimpleNamespace(name="Starter"),
        )
        payment = SimpleNamespace(
            id=1,
            member=member,
            amount=Decimal("700.00"),
            payment_method="cash",
            payment_status="paid",
            payment_date=datetime(2026, 7, 1, tzinfo=dt_timezone.utc),
            invoice_no="INV-000001",
            coverage_months=["2026-07"],
            get_payment_method_display=lambda: "Cash",
            get_payment_status_display=lambda: "Paid",
        )
        row = _row_from_payment(payment)
        self.assertEqual(row[0], "1")
        self.assertEqual(row[5], "700.00")
        self.assertEqual(len(EXPORT_HEADERS), 11)
        self.assertEqual(EXPORT_MAX_ROWS, 10_000)

        class FakeQS:
            def count(self):
                return 1

            def select_related(self, *args):
                return self

            def order_by(self, *args):
                return [payment]

        resp = build_payment_export_response(FakeQS(), fmt="csv", filter_label="2026-07")
        body = resp.content.decode("utf-8")
        self.assertIn("TOTAL", body)
        self.assertIn("700.00", body)

    def test_export_rejects_bad_format(self):
        class FakeQS:
            def count(self):
                return 0

            def select_related(self, *args):
                return self

            def order_by(self, *args):
                return []

        with self.assertRaises(ValidationError):
            build_payment_export_response(FakeQS(), fmt="docx")
