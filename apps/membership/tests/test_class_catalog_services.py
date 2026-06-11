from datetime import time

from django.test import TestCase
from django_tenants.utils import schema_context

from apps.identity.models import User
from apps.membership.models import GymClass, GymSchedule
from apps.membership.services.class_catalog import (
    ClassCatalogService,
    MandatoryTrainerRequired,
    PermissionDenied,
)
from apps.membership.services.class_schedule_sync import ClassScheduleSyncService
from apps.tenancy.models import Domain, Tenant
from apps.trainer.models import TrainerClass, TrainerProfile, TrainerSchedule


class UnifiedClassCatalogServiceTests(TestCase):
    def setUp(self):
        with schema_context('public'):
            self.public = Tenant.objects.create(
                schema_name='public',
                name='Public',
                slug='public',
                code='PUBCLS01',
                owner_email='root@classes.test',
                billing_email='root@classes.test',
                status='active',
                is_trial=False,
            )
            Domain.objects.get_or_create(
                domain='testserver',
                tenant=self.public,
                defaults={'is_primary': True},
            )
            self.tenant = Tenant.objects.create(
                schema_name='unified_class_test',
                name='Unified Class Tenant',
                slug='unified-class',
                code='UNICLS01',
                owner_email='admin@classes.test',
                billing_email='admin@classes.test',
                status='active',
                is_trial=False,
            )
            Domain.objects.create(domain='classes.testserver', tenant=self.tenant, is_primary=True)

        with schema_context(self.tenant.schema_name):
            self.admin = User.objects.create_superuser(
                email='admin@classes.test',
                password='StrongPass123!',
                tenant=self.tenant,
            )
            self.trainer_user = User.objects.create_user(
                email='trainer@classes.test',
                password='StrongPass123!',
                tenant=self.tenant,
                full_name='Ava Stone',
            )
            self.trainer_profile = TrainerProfile.objects.create(
                user=self.trainer_user,
                username='ava-stone',
                title='Yoga Instructor',
            )
            self.other_trainer_user = User.objects.create_user(
                email='other@classes.test',
                password='StrongPass123!',
                tenant=self.tenant,
                full_name='Kai Miles',
            )
            self.other_trainer_profile = TrainerProfile.objects.create(
                user=self.other_trainer_user,
                username='kai-miles',
                title='HIIT Coach',
            )

        self.admin_service = ClassCatalogService(user=self.admin)
        self.trainer_service = ClassCatalogService(user=self.trainer_user)

    def test_admin_create_requires_trainer(self):
        with schema_context(self.tenant.schema_name):
            with self.assertRaises(MandatoryTrainerRequired):
                self.admin_service.create_gym_class_from_admin({
                    'name': 'Sunrise Flow',
                    'class_type': 'yoga',
                    'level': 'beginner',
                })

    def test_admin_create_syncs_trainer_class(self):
        with schema_context(self.tenant.schema_name):
            gym_class = self.admin_service.create_gym_class_from_admin({
                'name': 'Sunrise Flow',
                'class_type': 'yoga',
                'level': 'beginner',
                'trainer_profile': self.trainer_profile.id,
                'duration_minutes': 45,
                'capacity': 18,
            })

            self.assertEqual(gym_class.trainer_profile_id, self.trainer_profile.id)
            self.assertIsNotNone(gym_class.trainer_class_id)
            trainer_class = TrainerClass.objects.get(pk=gym_class.trainer_class_id)
            self.assertEqual(trainer_class.name, 'Sunrise Flow')
            self.assertEqual(trainer_class.trainer_id, self.trainer_profile.id)

    def test_admin_update_reassigns_trainer(self):
        with schema_context(self.tenant.schema_name):
            gym_class = self.admin_service.create_gym_class_from_admin({
                'name': 'Power Ride',
                'class_type': 'cardio',
                'level': 'intermediate',
                'trainer_profile': self.trainer_profile.id,
            })
            updated = self.admin_service.update_gym_class_from_admin(
                gym_class,
                {'trainer_profile': self.other_trainer_profile.id},
            )
            updated.trainer_class.refresh_from_db()
            self.assertEqual(updated.trainer_profile_id, self.other_trainer_profile.id)
            self.assertEqual(updated.trainer_class.trainer_id, self.other_trainer_profile.id)

    def test_admin_update_cannot_remove_trainer(self):
        with schema_context(self.tenant.schema_name):
            gym_class = self.admin_service.create_gym_class_from_admin({
                'name': 'Core Burn',
                'class_type': 'strength',
                'level': 'advanced',
                'trainer_profile': self.trainer_profile.id,
            })
            with self.assertRaises(MandatoryTrainerRequired):
                self.admin_service.update_gym_class_from_admin(gym_class, {'trainer_profile': None})

    def test_trainer_create_syncs_gym_class(self):
        with schema_context(self.tenant.schema_name):
            trainer_class = self.trainer_service.create_trainer_class(
                self.trainer_profile,
                {
                    'name': 'Evening Stretch',
                    'category': 'yoga',
                    'difficulty_level': 'all',
                    'duration_minutes': 50,
                    'max_participants': 12,
                },
            )
            gym_class = trainer_class.gym_class
            self.assertIsNotNone(gym_class)
            self.assertEqual(gym_class.name, 'Evening Stretch')
            self.assertEqual(gym_class.trainer_profile_id, self.trainer_profile.id)

    def test_trainer_cannot_manage_other_trainer_class(self):
        with schema_context(self.tenant.schema_name):
            trainer_class = TrainerClass.objects.create(
                trainer=self.other_trainer_profile,
                name='Other Class',
            )
            with self.assertRaises(PermissionDenied):
                self.trainer_service.update_trainer_class(trainer_class, {'name': 'Hijacked'})

    def test_weekly_gym_schedule_syncs_trainer_schedule(self):
        with schema_context(self.tenant.schema_name):
            gym_class = self.admin_service.create_gym_class_from_admin({
                'name': 'Morning Yoga',
                'class_type': 'yoga',
                'level': 'beginner',
                'trainer_profile': self.trainer_profile.id,
            })
            gym_schedule = self.admin_service.create_gym_schedule_from_admin({
                'gym_class': gym_class.id,
                'title': 'Morning Yoga',
                'day_of_week': 'monday',
                'start_time': time(7, 0),
                'end_time': time(8, 0),
                'capacity': 15,
            })
            self.assertIsNotNone(gym_schedule.trainer_schedule_id)
            trainer_schedule = gym_schedule.trainer_schedule
            self.assertEqual(trainer_schedule.day_of_week, 'monday')
            self.assertIsNone(trainer_schedule.scheduled_date)

    def test_trainer_date_schedule_syncs_gym_schedule(self):
        with schema_context(self.tenant.schema_name):
            trainer_class = self.trainer_service.create_trainer_class(
                self.trainer_profile,
                {'name': 'HIIT Blast', 'category': 'hiit'},
            )
            trainer_schedule = self.trainer_service.create_trainer_schedule(
                self.trainer_profile,
                {
                    'trainer_class': trainer_class.id,
                    'scheduled_date': '2026-06-15',
                    'start_time': time(18, 0),
                    'end_time': time(19, 0),
                    'location': 'Studio A',
                },
            )
            gym_schedule = trainer_schedule.gym_schedule
            self.assertIsNotNone(gym_schedule)
            self.assertEqual(gym_schedule.recurrence_mode, 'one_off')
            self.assertEqual(str(gym_schedule.scheduled_date), '2026-06-15')

    def test_idempotent_gym_class_sync(self):
        with schema_context(self.tenant.schema_name):
            gym_class = self.admin_service.create_gym_class_from_admin({
                'name': 'Cycle',
                'class_type': 'cardio',
                'level': 'intermediate',
                'trainer_profile': self.trainer_profile.id,
            })
            first_id = gym_class.trainer_class_id
            ClassScheduleSyncService.sync_gym_class_to_trainer_class(gym_class)
            gym_class.refresh_from_db()
            self.assertEqual(gym_class.trainer_class_id, first_id)
            self.assertEqual(TrainerClass.objects.filter(pk=first_id).count(), 1)
