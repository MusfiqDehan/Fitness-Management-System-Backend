"""Tests for expired member credential cleanup scheduling helpers."""
from contextlib import nullcontext
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from apps.attendance.services.expired_member_credential_cleanup import (
    add_one_calendar_month,
    process_tenant_cleanup_slots,
)


class AddOneCalendarMonthTests(SimpleTestCase):
    def test_advances_month_and_clamps_day(self):
        dt = datetime(2026, 1, 31, 14, 30, tzinfo=timezone.get_current_timezone())
        next_dt = add_one_calendar_month(dt)
        self.assertEqual(next_dt.year, 2026)
        self.assertEqual(next_dt.month, 2)
        self.assertEqual(next_dt.day, 28)
        self.assertEqual(next_dt.hour, 14)


class ProcessTenantCleanupSlotsTests(SimpleTestCase):
    @patch(
        "apps.attendance.services.expired_member_credential_cleanup._current_tenant_has_preferences_feature",
        return_value=True,
    )
    @patch(
        "apps.attendance.services.expired_member_credential_cleanup.transaction.atomic",
        return_value=nullcontext(),
    )
    @patch(
        "apps.attendance.services.expired_member_credential_cleanup._queue_deletes_for_expired_members",
        return_value={"queued": 2, "skipped": 0, "failed": 0},
    )
    @patch("apps.attendance.services.expired_member_credential_cleanup.GymPreferences")
    def test_due_slot_advances_before_queue(
        self, mock_prefs_model, mock_queue, _mock_atomic, _mock_feature
    ):
        now = timezone.now()
        due = now - timedelta(minutes=5)
        prefs = MagicMock()
        prefs.payment_auto_delete_credentials_enabled = True
        prefs.payment_cleanup_run_at_1 = due
        prefs.payment_cleanup_run_at_2 = now + timedelta(days=10)
        mock_prefs_model.objects.select_for_update.return_value.filter.return_value.first.return_value = (
            prefs
        )

        result = process_tenant_cleanup_slots(now=now)

        self.assertTrue(result["acted"])
        self.assertEqual(len(result["slots"]), 1)
        self.assertEqual(result["slots"][0]["queued"], 2)
        # Replay safety: slot advanced (saved) before queue runs once.
        prefs.save.assert_called_once()
        mock_queue.assert_called_once()
        self.assertGreater(prefs.payment_cleanup_run_at_1, now)

    @patch(
        "apps.attendance.services.expired_member_credential_cleanup._current_tenant_has_preferences_feature",
        return_value=True,
    )
    @patch(
        "apps.attendance.services.expired_member_credential_cleanup.transaction.atomic",
        return_value=nullcontext(),
    )
    @patch(
        "apps.attendance.services.expired_member_credential_cleanup._queue_deletes_for_expired_members",
        return_value={"queued": 1, "skipped": 0, "failed": 0},
    )
    @patch("apps.attendance.services.expired_member_credential_cleanup.GymPreferences")
    def test_both_due_slots_queue_deletes_once(
        self, mock_prefs_model, mock_queue, _mock_atomic, _mock_feature
    ):
        now = timezone.now()
        prefs = MagicMock()
        prefs.payment_auto_delete_credentials_enabled = True
        prefs.payment_cleanup_run_at_1 = now - timedelta(minutes=10)
        prefs.payment_cleanup_run_at_2 = now - timedelta(minutes=5)
        mock_prefs_model.objects.select_for_update.return_value.filter.return_value.first.return_value = (
            prefs
        )

        result = process_tenant_cleanup_slots(now=now)

        self.assertTrue(result["acted"])
        self.assertEqual(len(result["slots"]), 2)
        mock_queue.assert_called_once()

    @patch(
        "apps.attendance.services.expired_member_credential_cleanup._current_tenant_has_preferences_feature",
        return_value=False,
    )
    def test_feature_disabled_skips_tenant(self, _mock_feature):
        result = process_tenant_cleanup_slots(now=timezone.now())
        self.assertFalse(result["acted"])
        self.assertEqual(result["reason"], "feature_disabled")

    @patch(
        "apps.attendance.services.expired_member_credential_cleanup._current_tenant_has_preferences_feature",
        return_value=True,
    )
    @patch(
        "apps.attendance.services.expired_member_credential_cleanup.transaction.atomic",
        return_value=nullcontext(),
    )
    @patch("apps.attendance.services.expired_member_credential_cleanup.GymPreferences")
    def test_disabled_toggle_noops(self, mock_prefs_model, _mock_atomic, _mock_feature):
        prefs = MagicMock()
        prefs.payment_auto_delete_credentials_enabled = False
        mock_prefs_model.objects.select_for_update.return_value.filter.return_value.first.return_value = (
            prefs
        )

        result = process_tenant_cleanup_slots(now=timezone.now())

        self.assertFalse(result["acted"])
        self.assertEqual(result["reason"], "disabled")
        prefs.save.assert_not_called()
