from __future__ import annotations

from typing import Any

from django.db import transaction

from apps.membership.models import GymClass, GymSchedule
from apps.trainer.models import TrainerClass, TrainerProfile, TrainerSchedule

from .class_schedule_sync import ClassScheduleSyncService


class ClassCatalogServiceError(Exception):
    """Base error for class catalog operations."""


class MandatoryTrainerRequired(ClassCatalogServiceError):
    """Raised when admin class operations omit trainer assignment."""


class PermissionDenied(ClassCatalogServiceError):
    """Raised when a user attempts an unauthorized class/schedule mutation."""


def _resolve_pk(value: Any) -> Any:
    return getattr(value, 'pk', value)


class ClassCatalogService:
    def __init__(self, *, user=None):
        self.user = user

    @transaction.atomic
    def create_gym_class_from_admin(self, data: dict[str, Any]) -> GymClass:
        trainer_profile_ref = data.get('trainer_profile') or data.get('trainer_profile_id')
        if not trainer_profile_ref:
            raise MandatoryTrainerRequired('Trainer assignment is required.')

        trainer_profile_id = _resolve_pk(trainer_profile_ref)
        trainer_profile = TrainerProfile.objects.filter(pk=trainer_profile_id, is_deleted=False).first()
        if trainer_profile is None:
            raise MandatoryTrainerRequired('Selected trainer was not found.')

        instructor = data.get('instructor') or trainer_profile.user.full_name
        gym_class = GymClass.objects.create(
            name=data['name'],
            class_type=data.get('class_type', 'other'),
            level=data.get('level', 'beginner'),
            instructor=instructor,
            trainer_profile=trainer_profile,
            duration_minutes=data.get('duration_minutes', 60),
            capacity=data.get('capacity', 20),
            description=data.get('description', ''),
            image_url=data.get('image_url', ''),
            is_published=data.get('is_published', False),
            is_active=data.get('is_active', True),
        )
        ClassScheduleSyncService.sync_gym_class_to_trainer_class(gym_class)
        gym_class.refresh_from_db()
        return gym_class

    @transaction.atomic
    def update_gym_class_from_admin(self, gym_class: GymClass, data: dict[str, Any]) -> GymClass:
        if 'trainer_profile' in data or 'trainer_profile_id' in data:
            trainer_profile_ref = data.get('trainer_profile') or data.get('trainer_profile_id')
            if not trainer_profile_ref:
                raise MandatoryTrainerRequired('Trainer assignment cannot be removed.')
            trainer_profile_id = _resolve_pk(trainer_profile_ref)
            trainer_profile = TrainerProfile.objects.filter(pk=trainer_profile_id, is_deleted=False).first()
            if trainer_profile is None:
                raise MandatoryTrainerRequired('Selected trainer was not found.')
            gym_class.trainer_profile = trainer_profile
            gym_class.instructor = data.get('instructor') or trainer_profile.user.full_name

        for field in ('name', 'class_type', 'level', 'duration_minutes', 'capacity', 'description', 'image_url', 'is_published', 'is_active'):
            if field in data:
                setattr(gym_class, field, data[field])

        if gym_class.trainer_profile is None:
            raise MandatoryTrainerRequired('Trainer assignment is required.')

        gym_class.save()
        ClassScheduleSyncService.sync_gym_class_to_trainer_class(gym_class)
        gym_class.refresh_from_db()
        return gym_class

    @transaction.atomic
    def create_trainer_class(self, trainer_profile: TrainerProfile, data: dict[str, Any]) -> TrainerClass:
        self._assert_trainer_owner(trainer_profile)
        trainer_class = TrainerClass.objects.create(
            trainer=trainer_profile,
            name=data['name'],
            description=data.get('description', ''),
            category=data.get('category', ''),
            difficulty_level=data.get('difficulty_level', 'all'),
            duration_minutes=data.get('duration_minutes', 60),
            max_participants=data.get('max_participants', 20),
            is_published=data.get('is_published', True),
            is_active=data.get('is_active', True),
        )
        ClassScheduleSyncService.sync_trainer_class_to_gym_class(trainer_class)
        trainer_class.refresh_from_db()
        if hasattr(trainer_profile, 'recalc_stats'):
            trainer_profile.recalc_stats()
        return trainer_class

    @transaction.atomic
    def update_trainer_class(self, trainer_class: TrainerClass, data: dict[str, Any]) -> TrainerClass:
        self._assert_trainer_owner(trainer_class.trainer)
        for field in (
            'name', 'description', 'category', 'difficulty_level',
            'duration_minutes', 'max_participants', 'is_published', 'is_active',
        ):
            if field in data:
                setattr(trainer_class, field, data[field])
        trainer_class.save()
        ClassScheduleSyncService.sync_trainer_class_to_gym_class(trainer_class)
        trainer_class.refresh_from_db()
        return trainer_class

    @transaction.atomic
    def create_gym_schedule_from_admin(self, data: dict[str, Any]) -> GymSchedule:
        gym_class = None
        gym_class_ref = data.get('gym_class')
        if gym_class_ref:
            gym_class = GymClass.objects.filter(pk=_resolve_pk(gym_class_ref), is_deleted=False).first()

        trainer_profile = None
        if gym_class and gym_class.trainer_profile:
            trainer_profile = gym_class.trainer_profile
        trainer_profile_ref = data.get('trainer_profile') or data.get('trainer_profile_id')
        if trainer_profile_ref:
            trainer_profile = TrainerProfile.objects.filter(
                pk=_resolve_pk(trainer_profile_ref),
                is_deleted=False,
            ).first()

        if trainer_profile is None:
            raise MandatoryTrainerRequired('Trainer assignment is required for schedules.')

        gym_schedule = GymSchedule.objects.create(
            gym_class=gym_class,
            trainer_profile=trainer_profile,
            title=data.get('title') or (gym_class.name if gym_class else ''),
            class_type=data.get('class_type') or (gym_class.class_type if gym_class else ''),
            instructor=data.get('instructor') or trainer_profile.user.full_name,
            recurrence_mode=data.get('recurrence_mode', 'weekly'),
            scheduled_date=data.get('scheduled_date'),
            day_of_week=data['day_of_week'],
            start_time=data['start_time'],
            end_time=data['end_time'],
            capacity=data.get('capacity', gym_class.capacity if gym_class else 20),
            is_published=data.get('is_published', False),
            is_active=data.get('is_active', True),
        )
        ClassScheduleSyncService.sync_gym_schedule_to_trainer_schedule(gym_schedule)
        gym_schedule.refresh_from_db()
        return gym_schedule

    @transaction.atomic
    def create_trainer_schedule(self, trainer_profile: TrainerProfile, data: dict[str, Any]) -> TrainerSchedule:
        self._assert_trainer_owner(trainer_profile)
        trainer_class_ref = data['trainer_class']
        trainer_class_id = getattr(trainer_class_ref, 'pk', trainer_class_ref)
        trainer_class = TrainerClass.objects.filter(
            pk=trainer_class_id,
            trainer=trainer_profile,
            is_deleted=False,
        ).first()
        if trainer_class is None:
            raise PermissionDenied('Class not found or not owned by this trainer.')

        trainer_schedule = TrainerSchedule.objects.create(
            trainer_class=trainer_class,
            trainer=trainer_profile,
            scheduled_date=data.get('scheduled_date'),
            day_of_week=data.get('day_of_week'),
            start_time=data['start_time'],
            end_time=data['end_time'],
            location=data.get('location', ''),
            room_number=data.get('room_number', ''),
            is_published=data.get('is_published', True),
            is_active=data.get('is_active', True),
        )
        ClassScheduleSyncService.sync_trainer_schedule_to_gym_schedule(trainer_schedule)
        trainer_schedule.refresh_from_db()
        return trainer_schedule

    def _assert_trainer_owner(self, trainer_profile: TrainerProfile) -> None:
        if self.user is None:
            return
        if getattr(self.user, 'is_superuser', False):
            return
        profile = getattr(self.user, 'trainer_profile', None)
        if profile is None or profile.id != trainer_profile.id:
            raise PermissionDenied('Trainers may only manage their own classes and schedules.')
