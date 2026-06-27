from datetime import datetime, time, timedelta

from django.test import TestCase
from django.utils import timezone
from django_tenants.utils import schema_context

from apps.identity.models import User
from apps.membership.models import Attendance, Member
from apps.membership.services.class_attendance import ClassAttendanceService, resolve_session_window
from apps.tenancy.models import Domain, Tenant
from apps.trainer.models import ScheduleBooking, TrainerClass, TrainerProfile, TrainerSchedule


class ClassAttendanceServiceTests(TestCase):
    def setUp(self):
        with schema_context('public'):
            self.public = Tenant.objects.create(
                schema_name='public',
                name='Public',
                slug='public',
                code='PUBATT01',
                owner_email='root@att.test',
                billing_email='root@att.test',
                status='active',
                is_trial=False,
            )
            Domain.objects.get_or_create(
                domain='testserver',
                tenant=self.public,
                defaults={'is_primary': True},
            )
            self.tenant = Tenant.objects.create(
                schema_name='class_att_test',
                name='Class Att Tenant',
                slug='class-att',
                code='CLATT01',
                owner_email='admin@att.test',
                billing_email='admin@att.test',
                status='active',
                is_trial=False,
            )
            Domain.objects.create(domain='att.testserver', tenant=self.tenant, is_primary=True)

        with schema_context(self.tenant.schema_name):
            self.member_user = User.objects.create_user(
                email='member@att.test',
                password='StrongPass123!',
                tenant=self.tenant,
                full_name='Pat Member',
            )
            self.member = Member.objects.create(
                user=self.member_user,
                full_name='Pat Member',
                email='member@att.test',
                phone_number='01700000003',
                is_active=True,
            )
            trainer_user = User.objects.create_user(
                email='trainer@att.test',
                password='StrongPass123!',
                tenant=self.tenant,
                full_name='Coach',
            )
            trainer = TrainerProfile.objects.create(user=trainer_user, username='coach-att')
            trainer_class = TrainerClass.objects.create(
                trainer=trainer,
                name='HIIT',
                duration_minutes=45,
                max_participants=10,
            )
            session_date = timezone.now().date()
            self.schedule = TrainerSchedule.objects.create(
                trainer_class=trainer_class,
                trainer=trainer,
                scheduled_date=session_date,
                start_time=time(10, 0),
                end_time=time(11, 0),
            )
            self.booking = ScheduleBooking.objects.create(
                schedule=self.schedule,
                member=self.member,
                status='confirmed',
                source='admin_assigned',
            )

    def test_manual_check_in_on_time(self):
        with schema_context(self.tenant.schema_name):
            session_date = self.schedule.scheduled_date
            start, _ = resolve_session_window(self.schedule, session_date)
            self.booking.check_in_time = start
            self.booking.save()
            result = ClassAttendanceService.compute_punctuality(self.booking)
            self.assertEqual(result['punctuality'], 'on_time')
            self.assertEqual(result['punctuality_source'], 'manual')

    def test_door_scan_match_marks_attended(self):
        with schema_context(self.tenant.schema_name):
            session_date = self.schedule.scheduled_date
            start, _ = resolve_session_window(self.schedule, session_date)
            Attendance.objects.create(
                member=self.member,
                entry_method='fingerprint',
                check_in_time=start + timedelta(minutes=5),
            )
            matched = ClassAttendanceService.try_match_member_check_in(
                self.member,
                start + timedelta(minutes=5),
            )
            self.assertEqual(matched, 1)
            self.booking.refresh_from_db()
            self.assertEqual(self.booking.status, 'attended')
            self.assertIsNotNone(self.booking.check_in_time)

    def test_absent_after_session_window(self):
        with schema_context(self.tenant.schema_name):
            _, end = resolve_session_window(self.schedule, self.schedule.scheduled_date)
            future = end + timedelta(hours=2)
            with self.settings(CLASS_ATTENDANCE_GRACE_AFTER_MINUTES=10):
                original_now = timezone.now
                try:
                    timezone.now = lambda: future
                    result = ClassAttendanceService.compute_punctuality(self.booking)
                finally:
                    timezone.now = original_now
            self.assertEqual(result['punctuality'], 'absent')

    def test_admin_override_takes_precedence(self):
        with schema_context(self.tenant.schema_name):
            self.booking.punctuality_override = 'on_time'
            self.booking.save(update_fields=['punctuality_override'])
            result = ClassAttendanceService.compute_punctuality(self.booking)
            self.assertEqual(result['punctuality'], 'on_time')
            self.assertEqual(result['punctuality_source'], 'admin_override')

    def test_set_punctuality_override_clears_to_auto(self):
        with schema_context(self.tenant.schema_name):
            ClassAttendanceService.set_punctuality_override(self.booking, 'late', user=self.member_user)
            self.booking.refresh_from_db()
            self.assertEqual(self.booking.punctuality_override, 'late')
            ClassAttendanceService.set_punctuality_override(self.booking, None, user=self.member_user)
            self.booking.refresh_from_db()
            self.assertIsNone(self.booking.punctuality_override)
