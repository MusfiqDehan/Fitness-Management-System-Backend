from datetime import timedelta

from django.utils import timezone
from django_tenants.utils import schema_context

from apps.attendance.services.session import DUPLICATE_PUNCH_WINDOW, apply_member_punch
from apps.membership.models import Attendance, Member
from apps.tenancy.models import Domain, Tenant
from django.test import TestCase


class ApplyMemberPunchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant(schema_name="punchdeb", name="Punch Debounce Gym")
        cls.tenant.save()
        Domain.objects.get_or_create(
            domain="punchdeb.testserver",
            tenant=cls.tenant,
            defaults={"is_primary": True},
        )

    def test_ignores_second_punch_within_60_seconds(self):
        with schema_context(self.tenant.schema_name):
            member = Member.objects.create(
                full_name="Debounced Member",
                phone_number="01700002001",
                start_date=timezone.now().date(),
            )
            now = timezone.now()

            first = apply_member_punch(
                member,
                entry_method="fingerprint",
                device_id="SN-1",
                at=now,
            )
            second = apply_member_punch(
                member,
                entry_method="fingerprint",
                device_id="SN-1",
                at=now + timedelta(seconds=30),
            )

            self.assertEqual(first, "checked_in")
            self.assertIsNone(second)
            self.assertEqual(Attendance.objects.filter(member=member).count(), 1)
            self.assertIsNone(Attendance.objects.get(member=member).check_out_time)

    def test_checks_out_after_60_seconds(self):
        with schema_context(self.tenant.schema_name):
            member = Member.objects.create(
                full_name="Checkout Member",
                phone_number="01700002002",
                start_date=timezone.now().date(),
            )
            now = timezone.now()

            apply_member_punch(member, entry_method="fingerprint", device_id="SN-1", at=now)
            action = apply_member_punch(
                member,
                entry_method="card",
                device_id="SN-1",
                at=now + DUPLICATE_PUNCH_WINDOW + timedelta(seconds=1),
            )

            self.assertEqual(action, "checked_out")
            attendance = Attendance.objects.get(member=member)
            self.assertIsNotNone(attendance.check_out_time)

    def test_card_then_fingerprint_toggle_same_member(self):
        with schema_context(self.tenant.schema_name):
            member = Member.objects.create(
                full_name="Dual Cred Member",
                phone_number="01700002003",
                start_date=timezone.now().date(),
            )
            base = timezone.now().replace(microsecond=0)

            self.assertEqual(
                apply_member_punch(
                    member,
                    entry_method="card",
                    device_id="SN-1",
                    at=base,
                ),
                "checked_in",
            )
            self.assertEqual(
                apply_member_punch(
                    member,
                    entry_method="fingerprint",
                    device_id="SN-1",
                    at=base + DUPLICATE_PUNCH_WINDOW + timedelta(seconds=5),
                ),
                "checked_out",
            )
            self.assertEqual(
                apply_member_punch(
                    member,
                    entry_method="card",
                    device_id="SN-1",
                    at=base + (DUPLICATE_PUNCH_WINDOW * 2) + timedelta(seconds=10),
                ),
                None,
            )
            self.assertEqual(Attendance.objects.filter(member=member).count(), 1)

    def test_allows_new_check_in_on_next_day(self):
        with schema_context(self.tenant.schema_name):
            member = Member.objects.create(
                full_name="Next Day Member",
                phone_number="01700002004",
                start_date=timezone.now().date(),
            )
            day_one = timezone.now().replace(hour=9, minute=0, second=0, microsecond=0)
            day_two = day_one + timedelta(days=1)

            apply_member_punch(member, entry_method="fingerprint", device_id="SN-1", at=day_one)
            apply_member_punch(
                member,
                entry_method="fingerprint",
                device_id="SN-1",
                at=day_one + DUPLICATE_PUNCH_WINDOW + timedelta(seconds=5),
            )
            action = apply_member_punch(
                member,
                entry_method="card",
                device_id="SN-1",
                at=day_two,
            )

            self.assertEqual(action, "checked_in")
            self.assertEqual(Attendance.objects.filter(member=member).count(), 2)

    def test_ignores_check_in_when_daily_session_already_completed(self):
        with schema_context(self.tenant.schema_name):
            member = Member.objects.create(
                full_name="Completed Day Member",
                phone_number="01700002005",
                start_date=timezone.now().date(),
            )
            base = timezone.now().replace(microsecond=0)

            apply_member_punch(member, entry_method="fingerprint", device_id="SN-1", at=base)
            apply_member_punch(
                member,
                entry_method="card",
                device_id="SN-1",
                at=base + DUPLICATE_PUNCH_WINDOW + timedelta(seconds=5),
            )
            extra = apply_member_punch(
                member,
                entry_method="fingerprint",
                device_id="SN-1",
                at=base + timedelta(hours=4),
            )

            self.assertIsNone(extra)
            self.assertEqual(Attendance.objects.filter(member=member).count(), 1)
