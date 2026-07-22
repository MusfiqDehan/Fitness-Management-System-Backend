"""Tests for payment-driven member end_date renewal."""
from datetime import timedelta
from unittest.mock import MagicMock

from django.test import SimpleTestCase
from django.utils import timezone

from apps.billing.services.member_renewal import apply_paid_payment
from apps.membership.models import Payment


class ApplyPaidPaymentTests(SimpleTestCase):
    def _payment(self, *, end_date, payment_date, coverage_months, duration=30):
        member = MagicMock()
        member.end_date = end_date
        member.member_package = MagicMock(duration_in_days=duration)
        member.discount_usages = MagicMock()
        # payment.discount_usages.all() is called on payment, not member
        payment = MagicMock()
        payment.payment_status = Payment.STATUS_PAID
        payment.payment_type = "package"
        payment.member = member
        payment.payment_date = payment_date
        payment.coverage_months = coverage_months
        payment.coverage_month_count = len(coverage_months)
        payment.discount_usages.all.return_value = []
        return payment, member

    def test_expired_member_extends_from_payment_date(self):
        today = timezone.now().date()
        payment_date = timezone.now() - timedelta(days=2)
        payment, member = self._payment(
            end_date=today - timedelta(days=10),
            payment_date=payment_date,
            coverage_months=["2026-01", "2026-02"],
            duration=30,
        )

        self.assertTrue(apply_paid_payment(payment, previous_status=Payment.STATUS_DUE))

        expected = payment_date.date() + timedelta(days=60)
        self.assertEqual(member.end_date, expected)
        self.assertEqual(member.payment_status, "paid")
        self.assertTrue(member.is_active)
        member.save.assert_called_once()

    def test_active_member_extends_from_current_end_date(self):
        today = timezone.now().date()
        current_end = today + timedelta(days=5)
        payment_date = timezone.now()
        payment, member = self._payment(
            end_date=current_end,
            payment_date=payment_date,
            coverage_months=["2026-03"],
            duration=30,
        )

        self.assertTrue(apply_paid_payment(payment, previous_status=Payment.STATUS_DUE))
        self.assertEqual(member.end_date, current_end + timedelta(days=30))
