from datetime import time, timedelta

from django.urls import reverse
from django.utils import timezone
from django_tenants.utils import schema_context
from rest_framework import status
from rest_framework.test import APITestCase

from apps.identity.models import User
from apps.membership.models import Member
from apps.membership.services.class_catalog import ClassCatalogService
from apps.tenancy.models import Domain, Tenant
from apps.trainer.models import TrainerProfile


class ClassDetailAPITests(APITestCase):
    def setUp(self):
        with schema_context('public'):
            self.public = Tenant.objects.create(
                schema_name='public',
                name='Public',
                slug='public',
                code='PUBAPI01',
                owner_email='root@api.test',
                billing_email='root@api.test',
                status='active',
                is_trial=False,
            )
            Domain.objects.get_or_create(
                domain='testserver',
                tenant=self.public,
                defaults={'is_primary': True},
            )
            self.tenant = Tenant.objects.create(
                schema_name='class_detail_api',
                name='Class Detail API Tenant',
                slug='class-detail-api',
                code='CLAPI01',
                owner_email='admin@api.test',
                billing_email='admin@api.test',
                status='active',
                is_trial=False,
            )
            Domain.objects.create(domain='api.testserver', tenant=self.tenant, is_primary=True)

        with schema_context(self.tenant.schema_name):
            self.admin = User.objects.create_superuser(
                email='admin@api.test',
                password='StrongPass123!',
                tenant=self.tenant,
            )
            trainer_user = User.objects.create_user(
                email='trainer@api.test',
                password='StrongPass123!',
                tenant=self.tenant,
                full_name='Coach',
            )
            self.trainer = TrainerProfile.objects.create(user=trainer_user, username='coach-api')
            member_user = User.objects.create_user(
                email='member@api.test',
                password='StrongPass123!',
                tenant=self.tenant,
                full_name='Member One',
            )
            self.member = Member.objects.create(
                user=member_user,
                full_name='Member One',
                email='member@api.test',
                phone_number='01700000099',
                is_active=True,
            )
            catalog = ClassCatalogService(user=self.admin)
            self.gym_class = catalog.create_gym_class_from_admin({
                'name': 'API Yoga',
                'class_type': 'yoga',
                'level': 'beginner',
                'trainer_profile': self.trainer,
                'duration_minutes': 60,
                'capacity': 5,
            })
            tomorrow = timezone.now().date() + timedelta(days=1)
            catalog.create_gym_schedule_from_admin({
                'title': 'API Yoga',
                'gym_class': self.gym_class,
                'trainer_profile': self.trainer,
                'recurrence_mode': 'one_off',
                'scheduled_date': tomorrow,
                'day_of_week': 'monday',
                'start_time': time(9, 0),
                'end_time': time(10, 0),
                'capacity': 5,
            })

        self.client.force_authenticate(user=self.admin)

    def test_class_detail_endpoint(self):
        url = reverse('membership:gymclass-detail-composite', kwargs={'pk': self.gym_class.id})
        response = self.client.get(url, HTTP_HOST='api.testserver')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['name'], 'API Yoga')
        self.assertIn('active_enrollments', response.data)

    def test_assign_and_list_members(self):
        assign_url = reverse('membership:gymclass-members', kwargs={'pk': self.gym_class.id})
        response = self.client.post(
            assign_url,
            {'member_ids': [self.member.id], 'sync_future_sessions': True},
            format='json',
            HTTP_HOST='api.testserver',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        list_response = self.client.get(assign_url, HTTP_HOST='api.testserver')
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(list_response.data['count'], 1)

    def test_update_attendance_punctuality(self):
        assign_url = reverse('membership:gymclass-members', kwargs={'pk': self.gym_class.id})
        self.client.post(
            assign_url,
            {'member_ids': [self.member.id], 'sync_future_sessions': True},
            format='json',
            HTTP_HOST='api.testserver',
        )
        from apps.trainer.models import ScheduleBooking

        with schema_context(self.tenant.schema_name):
            booking = ScheduleBooking.objects.filter(
                member=self.member,
                schedule__trainer_class_id=self.gym_class.trainer_class_id,
            ).first()
            self.assertIsNotNone(booking)
            booking_id = booking.id

        patch_url = reverse(
            'membership:gymclass-attendance-item',
            kwargs={'pk': self.gym_class.id, 'booking_id': booking_id},
        )
        response = self.client.patch(
            patch_url,
            {'punctuality': 'late'},
            format='json',
            HTTP_HOST='api.testserver',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['punctuality'], 'late')
        self.assertEqual(response.data['punctuality_source'], 'admin_override')

    def test_my_enrollments_as_member(self):
        assign_url = reverse('membership:gymclass-members', kwargs={'pk': self.gym_class.id})
        self.client.post(
            assign_url,
            {'member_ids': [self.member.id]},
            format='json',
            HTTP_HOST='api.testserver',
        )
        member_user = User.objects.get(email='member@api.test')
        self.client.force_authenticate(user=member_user)
        enroll_url = reverse('membership:my-class-enrollments')
        response = self.client.get(enroll_url, HTTP_HOST='api.testserver')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['class_name'], 'API Yoga')
