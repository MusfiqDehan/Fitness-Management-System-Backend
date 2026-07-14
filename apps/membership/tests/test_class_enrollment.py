from datetime import time, timedelta

from django.test import TestCase
from django.utils import timezone
from django_tenants.utils import schema_context

from apps.identity.models import User
from apps.membership.models import ClassEnrollment, GymClass, GymSchedule, Member
from apps.membership.services.class_enrollment import (
    CapacityExceeded,
    ClassEnrollmentService,
)
from apps.tenancy.models import Domain, Tenant
from apps.trainer.models import ScheduleBooking, TrainerClass, TrainerProfile, TrainerSchedule


class ClassEnrollmentServiceTests(TestCase):
    def setUp(self):
        with schema_context('public'):
            self.public = Tenant.objects.create(
                schema_name='public',
                name='Public',
                slug='public',
                code='PUBEN01',
                owner_email='root@enroll.test',
                billing_email='root@enroll.test',
                status='active',
                is_trial=False,
            )
            Domain.objects.get_or_create(
                domain='testserver',
                tenant=self.public,
                defaults={'is_primary': True},
            )
            self.tenant = Tenant.objects.create(
                schema_name='class_enroll_test',
                name='Class Enroll Tenant',
                slug='class-enroll',
                code='CLEN01',
                owner_email='admin@enroll.test',
                billing_email='admin@enroll.test',
                status='active',
                is_trial=False,
            )
            Domain.objects.create(domain='enroll.testserver', tenant=self.tenant, is_primary=True)

        with schema_context(self.tenant.schema_name):
            self.admin = User.objects.create_superuser(
                email='admin@enroll.test',
                password='StrongPass123!',
                tenant=self.tenant,
            )
            self.trainer_user = User.objects.create_user(
                email='trainer@enroll.test',
                password='StrongPass123!',
                tenant=self.tenant,
                full_name='Coach Lee',
            )
            self.trainer_profile = TrainerProfile.objects.create(
                user=self.trainer_user,
                username='coach-lee',
            )
            self.member_user = User.objects.create_user(
                email='member@enroll.test',
                password='StrongPass123!',
                tenant=self.tenant,
                full_name='Sam Member',
            )
            self.member = Member.objects.create(
                user=self.member_user,
                full_name='Sam Member',
                email='member@enroll.test',
                phone_number='01700000001',
                is_active=True,
            )
            self.member2_user = User.objects.create_user(
                email='member2@enroll.test',
                password='StrongPass123!',
                tenant=self.tenant,
                full_name='Alex Member',
            )
            self.member2 = Member.objects.create(
                user=self.member2_user,
                full_name='Alex Member',
                email='member2@enroll.test',
                phone_number='01700000002',
                is_active=True,
            )
            from apps.membership.services.class_catalog import ClassCatalogService
            catalog = ClassCatalogService(user=self.admin)
            self.gym_class = catalog.create_gym_class_from_admin({
                'name': 'Morning Yoga',
                'class_type': 'yoga',
                'level': 'beginner',
                'trainer_profile': self.trainer_profile,
                'duration_minutes': 60,
                'capacity': 2,
            })
            tomorrow = timezone.now().date() + timedelta(days=1)
            self.gym_schedule = catalog.create_gym_schedule_from_admin({
                'title': 'Morning Yoga',
                'gym_class': self.gym_class,
                'trainer_profile': self.trainer_profile,
                'recurrence_mode': 'one_off',
                'scheduled_date': tomorrow,
                'day_of_week': 'monday',
                'start_time': time(9, 0),
                'end_time': time(10, 0),
                'capacity': 2,
            })

        self.service = ClassEnrollmentService(user=self.admin)

    def test_enroll_member_creates_enrollment_and_booking(self):
        with schema_context(self.tenant.schema_name):
            enrollments = self.service.enroll_members(
                self.gym_class,
                [self.member.id],
                sync_future_sessions=True,
            )
            self.assertEqual(len(enrollments), 1)
            self.assertEqual(enrollments[0].status, 'active')
            self.assertTrue(
                ScheduleBooking.objects.filter(
                    member=self.member,
                    source='admin_assigned',
                    is_deleted=False,
                ).exists()
            )

    def test_capacity_exceeded_raises(self):
        with schema_context(self.tenant.schema_name):
            self.service.enroll_members(self.gym_class, [self.member.id])
            with self.assertRaises(CapacityExceeded):
                self.service.enroll_members(self.gym_class, [self.member2.id])

    def test_remove_member_cancels_future_bookings(self):
        with schema_context(self.tenant.schema_name):
            self.service.enroll_members(self.gym_class, [self.member.id], sync_future_sessions=True)
            removed = self.service.remove_members(self.gym_class, [self.member.id])
            self.assertEqual(removed, 1)
            enrollment = ClassEnrollment.objects.get(gym_class=self.gym_class, member=self.member)
            self.assertEqual(enrollment.status, 'removed')
            self.assertFalse(
                ScheduleBooking.objects.filter(
                    member=self.member,
                    status='confirmed',
                    is_deleted=False,
                ).exists()
            )
