"""Extend member membership dates when a package/monthly payment is marked paid."""
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from apps.membership.models import Member, Payment


def apply_paid_payment(payment: Payment, *, previous_status: str | None = None) -> bool:
    """Update member renewal fields when payment transitions to paid.

    Returns True if member was updated.
    """
    if payment.payment_status != Payment.STATUS_PAID:
        return False

    if previous_status == Payment.STATUS_PAID:
        return False

    if payment.payment_type not in ("package", "monthly"):
        return False

    member = payment.member
    if member is None:
        return False

    today = timezone.now().date()
    duration = 30
    if member.member_package and member.member_package.duration_in_days:
        duration = member.member_package.duration_in_days

    base = member.end_date if member.end_date and member.end_date >= today else today
    member.end_date = base + timedelta(days=duration)
    member.payment_status = "paid"
    member.is_active = True
    member.save(update_fields=["end_date", "payment_status", "is_active", "updated_at"])
    return True
