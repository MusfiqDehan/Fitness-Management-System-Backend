from datetime import time

from django.urls import reverse
from django_tenants.utils import schema_context
from rest_framework import status
from rest_framework.test import APIRequestFactory, APITestCase, force_authenticate

from apps.identity.models import User
from apps.membership.services.class_catalog import ClassCatalogService
from apps.tenancy.models import Domain, Feature, Tenant, TenantFeatureFlag

from .models import TrainerClass, TrainerProfile, TrainerSchedule
from .views import TrainerClassView, TrainerScheduleView
from apps.membership.views import GymScheduleView


class TrainerWorkspaceAutoTrainerTests(APITestCase):
    def setUp(self):
        with schema_context('public'):
            self.public = Tenant.objects.create(
                schema_name='public',
                name='Public',
                slug='public',
                code='PUBTRNWS01',
                owner_email='root@trainer-ws.test',
                billing_email='root@trainer-ws.test',
                status='active',
                is_trial=False,
            )
            Domain.objects.get_or_create(
                domain='testserver',
                tenant=self.public,
                defaults={'is_primary': True},
            )
            self.tenant = Tenant.objects.create(
                schema_name='trainer_ws_auto',
                name='Trainer WS Auto Tenant',
                slug='trainer-ws-auto',
                code='TRNWS001',
                owner_email='admin@trainer-ws.test',
                billing_email='admin@trainer-ws.test',
                status='active',
                is_trial=False,
            )
            Domain.objects.create(domain='trainer-ws.testserver', tenant=self.tenant, is_primary=True)

        with schema_context(self.tenant.schema_name):
            self.admin = User.objects.create_superuser(
                email='admin@trainer-ws.test',
                password='StrongPass123!',
                tenant=self.tenant,
            )
            self.trainer_user = User.objects.create_user(
                email='trainer@trainer-ws.test',
                password='StrongPass123!',
                tenant=self.tenant,
                full_name='Ava Stone',
                role='trainer',
            )
            self.trainer_profile = TrainerProfile.objects.create(
                user=self.trainer_user,
                username='ava-stone',
                title='Yoga Instructor',
            )
            self.other_trainer_user = User.objects.create_user(
                email='other@trainer-ws.test',
                password='StrongPass123!',
                tenant=self.tenant,
                full_name='Kai Miles',
                role='trainer',
            )
            self.other_trainer_profile = TrainerProfile.objects.create(
                user=self.other_trainer_user,
                username='kai-miles',
                title='HIIT Coach',
            )

        self.enable_feature(self.tenant, 'instructors')
        self.enable_feature(self.tenant, 'trainer')
        self.enable_feature(self.tenant, 'classes')

        self.factory = APIRequestFactory()
        self.admin_service = ClassCatalogService(user=self.admin)

    @staticmethod
    def enable_feature(tenant, feature_key: str):
        with schema_context('public'):
            feature, _ = Feature.objects.get_or_create(
                key=feature_key,
                defaults={'name': feature_key, 'sort_order': 0},
            )
            TenantFeatureFlag.objects.update_or_create(
                tenant=tenant,
                feature=feature,
                defaults={
                    'is_enabled': True,
                    'source': TenantFeatureFlag.SOURCE_OVERRIDE,
                },
            )

    @staticmethod
    def _response_items(data):
        if isinstance(data, list):
            return data
        return data.get('results', [])

    def _post_class(self, payload, user=None):
        path = reverse('trainer:trainer-class-list')
        request = self.factory.post(path, payload, format='json')
        request.tenant = self.tenant
        force_authenticate(request, user=user or self.trainer_user)
        with schema_context(self.tenant.schema_name):
            return TrainerClassView.as_view()(request)

    def _get_classes(self, user=None):
        path = reverse('trainer:trainer-class-list')
        request = self.factory.get(path)
        request.tenant = self.tenant
        force_authenticate(request, user=user or self.trainer_user)
        with schema_context(self.tenant.schema_name):
            return TrainerClassView.as_view()(request)

    def _post_schedule(self, payload, user=None):
        path = reverse('trainer:trainer-schedule-list')
        request = self.factory.post(path, payload, format='json')
        request.tenant = self.tenant
        force_authenticate(request, user=user or self.trainer_user)
        with schema_context(self.tenant.schema_name):
            return TrainerScheduleView.as_view()(request)

    def _get_schedules(self, user=None):
        path = reverse('trainer:trainer-schedule-list')
        request = self.factory.get(path)
        request.tenant = self.tenant
        force_authenticate(request, user=user or self.trainer_user)
        with schema_context(self.tenant.schema_name):
            return TrainerScheduleView.as_view()(request)

    def _get_gym_schedules(self, user=None):
        path = reverse('membership:gymschedule-list')
        request = self.factory.get(path)
        request.tenant = self.tenant
        force_authenticate(request, user=user or self.admin)
        with schema_context(self.tenant.schema_name):
            return GymScheduleView.as_view()(request)

    def test_trainer_create_class_without_trainer_field(self):
        response = self._post_class({
            'name': 'Morning Flow',
            'category': 'yoga',
            'difficulty_level': 'all',
            'duration_minutes': 60,
            'max_participants': 20,
        })

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['trainer'], self.trainer_profile.id)

    def test_trainer_create_class_with_foreign_trainer_id_returns_403(self):
        response = self._post_class({
            'name': 'Hijacked Flow',
            'category': 'yoga',
            'trainer': self.other_trainer_profile.id,
        })

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_trainer_create_schedule_without_trainer_field(self):
        with schema_context(self.tenant.schema_name):
            trainer_class = TrainerClass.objects.create(
                trainer=self.trainer_profile,
                name='Evening Yoga',
                category='yoga',
            )

        response = self._post_schedule({
            'trainer_class': trainer_class.id,
            'scheduled_date': '2026-06-20',
            'start_time': '18:00:00',
            'end_time': '19:00:00',
            'location': 'Studio A',
        })

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['trainer'], self.trainer_profile.id)

    def test_trainer_create_schedule_with_foreign_trainer_id_returns_403(self):
        with schema_context(self.tenant.schema_name):
            trainer_class = TrainerClass.objects.create(
                trainer=self.trainer_profile,
                name='Evening Yoga',
                category='yoga',
            )

        response = self._post_schedule({
            'trainer_class': trainer_class.id,
            'trainer': self.other_trainer_profile.id,
            'scheduled_date': '2026-06-20',
            'start_time': '18:00:00',
            'end_time': '19:00:00',
        })

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_trainer_cannot_create_schedule_for_other_trainer_class(self):
        with schema_context(self.tenant.schema_name):
            other_class = TrainerClass.objects.create(
                trainer=self.other_trainer_profile,
                name='Other Class',
                category='hiit',
            )

        response = self._post_schedule({
            'trainer_class': other_class.id,
            'scheduled_date': '2026-06-20',
            'start_time': '18:00:00',
            'end_time': '19:00:00',
        })

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_create_class_without_trainer_returns_400(self):
        response = self._post_class(
            {
                'name': 'Admin Missing Trainer',
                'category': 'yoga',
            },
            user=self.admin,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_admin_assigned_class_appears_in_trainer_list(self):
        with schema_context(self.tenant.schema_name):
            gym_class = self.admin_service.create_gym_class_from_admin({
                'name': 'Admin Assigned Yoga',
                'class_type': 'yoga',
                'level': 'beginner',
                'trainer_profile': self.trainer_profile.id,
            })
            trainer_class_id = gym_class.trainer_class_id

        response = self._get_classes()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [item['id'] for item in self._response_items(response.data)]
        self.assertIn(trainer_class_id, ids)

    def test_admin_assigned_schedule_appears_in_trainer_list(self):
        with schema_context(self.tenant.schema_name):
            gym_class = self.admin_service.create_gym_class_from_admin({
                'name': 'Admin Assigned Spin',
                'class_type': 'cardio',
                'level': 'intermediate',
                'trainer_profile': self.trainer_profile.id,
            })
            gym_schedule = self.admin_service.create_gym_schedule_from_admin({
                'gym_class': gym_class.id,
                'title': 'Admin Assigned Spin',
                'day_of_week': 'tuesday',
                'start_time': time(9, 0),
                'end_time': time(10, 0),
            })
            trainer_schedule_id = gym_schedule.trainer_schedule_id

        response = self._get_schedules()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [item['id'] for item in self._response_items(response.data)]
        self.assertIn(trainer_schedule_id, ids)

    def test_trainer_created_schedule_appears_in_admin_gym_schedule_list(self):
        class_response = self._post_class({
            'name': 'Sunset Yoga',
            'category': 'yoga',
            'difficulty_level': 'all',
            'duration_minutes': 60,
            'max_participants': 12,
        })
        self.assertEqual(class_response.status_code, status.HTTP_201_CREATED)
        trainer_class_id = class_response.data['id']

        schedule_response = self._post_schedule({
            'trainer_class': trainer_class_id,
            'scheduled_date': '2026-06-20',
            'start_time': '18:00:00',
            'end_time': '19:00:00',
            'location': 'Studio B',
        })
        self.assertEqual(schedule_response.status_code, status.HTTP_201_CREATED)

        admin_response = self._get_gym_schedules(user=self.admin)
        self.assertEqual(admin_response.status_code, status.HTTP_200_OK)
        items = self._response_items(admin_response.data)
        self.assertGreaterEqual(len(items), 1)
        synced = next((item for item in items if item.get('trainer_schedule') == schedule_response.data['id']), None)
        self.assertIsNotNone(synced)
        self.assertEqual(synced['recurrence_mode'], 'one_off')
        self.assertEqual(synced['day_of_week'], 'saturday')
        self.assertEqual(synced['scheduled_date'], '2026-06-20')
