from django.db import models
from django.test import SimpleTestCase

from apps.membership.models import GymClass, GymSchedule
from apps.trainer.models import TrainerClass, TrainerSchedule


class UnifiedClassScheduleModelFieldTests(SimpleTestCase):
    def _field_names(self, model):
        return {field.name for field in model._meta.get_fields()}

    def test_gym_class_has_trainer_link_fields(self):
        names = self._field_names(GymClass)
        self.assertIn('trainer_profile', names)
        self.assertIn('trainer_class', names)

    def test_gym_class_trainer_class_link_is_one_to_one(self):
        field = GymClass._meta.get_field('trainer_class')
        self.assertIsInstance(field, models.OneToOneField)
        self.assertTrue(field.null)
        self.assertTrue(field.blank)

    def test_trainer_class_has_reverse_gym_class_link(self):
        field = TrainerClass._meta.get_field('gym_class')
        self.assertIsInstance(field, models.OneToOneRel)

    def test_gym_schedule_has_sync_fields(self):
        names = self._field_names(GymSchedule)
        self.assertIn('trainer_schedule', names)
        self.assertIn('recurrence_mode', names)
        self.assertIn('scheduled_date', names)
        self.assertIn('trainer_profile', names)

    def test_gym_schedule_recurrence_mode_defaults_weekly(self):
        field = GymSchedule._meta.get_field('recurrence_mode')
        self.assertEqual(field.default, 'weekly')

    def test_trainer_schedule_has_sync_fields(self):
        names = self._field_names(TrainerSchedule)
        self.assertIn('day_of_week', names)
        self.assertIn('gym_schedule', names)
        self.assertIsInstance(TrainerSchedule._meta.get_field('gym_schedule'), models.OneToOneRel)

    def test_trainer_schedule_scheduled_date_nullable(self):
        field = TrainerSchedule._meta.get_field('scheduled_date')
        self.assertTrue(field.null)
        self.assertTrue(field.blank)
