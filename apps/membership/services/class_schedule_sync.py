from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import transaction

from apps.membership.models import GymClass, GymSchedule
from apps.trainer.models import TrainerClass, TrainerSchedule, ScheduleBooking

if TYPE_CHECKING:
    from apps.trainer.models import TrainerProfile


CLASS_TYPE_LABELS = dict(GymClass.CLASS_TYPES)
LEVEL_TO_DIFFICULTY = {
    'beginner': 'beginner',
    'intermediate': 'intermediate',
    'advanced': 'advanced',
}
DIFFICULTY_TO_LEVEL = {
    'beginner': 'beginner',
    'intermediate': 'intermediate',
    'advanced': 'advanced',
    'all': 'beginner',
}


class ClassScheduleSyncService:
    """Keeps gym catalog and trainer workspace class/schedule records in sync."""

    @classmethod
    @transaction.atomic
    def sync_gym_class_to_trainer_class(cls, gym_class: GymClass) -> TrainerClass:
        trainer_profile = gym_class.trainer_profile
        if trainer_profile is None:
            raise ValueError('GymClass requires trainer_profile before sync.')

        category = CLASS_TYPE_LABELS.get(gym_class.class_type, gym_class.class_type)
        difficulty = LEVEL_TO_DIFFICULTY.get(gym_class.level, 'beginner')
        instructor_name = gym_class.instructor or trainer_profile.user.full_name

        trainer_class = gym_class.trainer_class
        if trainer_class is None:
            trainer_class = TrainerClass.objects.create(
                trainer=trainer_profile,
                name=gym_class.name,
                description=gym_class.description,
                category=category,
                difficulty_level=difficulty,
                duration_minutes=gym_class.duration_minutes,
                max_participants=gym_class.capacity,
                is_active=gym_class.is_active,
                is_published=gym_class.is_published,
            )
            gym_class.trainer_class = trainer_class
            gym_class.instructor = instructor_name
            gym_class.save(update_fields=['trainer_class', 'instructor', 'updated_at'])
            return trainer_class

        trainer_class.trainer = trainer_profile
        trainer_class.name = gym_class.name
        trainer_class.description = gym_class.description
        trainer_class.category = category
        trainer_class.difficulty_level = difficulty
        trainer_class.duration_minutes = gym_class.duration_minutes
        trainer_class.max_participants = gym_class.capacity
        trainer_class.is_active = gym_class.is_active
        trainer_class.is_published = gym_class.is_published
        trainer_class.save()
        gym_class.instructor = instructor_name
        gym_class.save(update_fields=['instructor', 'updated_at'])
        return trainer_class

    @classmethod
    @transaction.atomic
    def sync_trainer_class_to_gym_class(cls, trainer_class: TrainerClass) -> GymClass:
        trainer_profile = trainer_class.trainer
        gym_class = getattr(trainer_class, 'gym_class', None)

        class_type = trainer_class.category.lower() if trainer_class.category else 'other'
        valid_types = {choice[0] for choice in GymClass.CLASS_TYPES}
        if class_type not in valid_types:
            class_type = 'other'

        level = DIFFICULTY_TO_LEVEL.get(trainer_class.difficulty_level, 'beginner')
        instructor_name = trainer_profile.user.full_name

        if gym_class is None:
            gym_class = GymClass.objects.create(
                name=trainer_class.name,
                class_type=class_type,
                level=level,
                instructor=instructor_name,
                trainer_profile=trainer_profile,
                trainer_class=trainer_class,
                duration_minutes=trainer_class.duration_minutes,
                capacity=trainer_class.max_participants,
                description=trainer_class.description,
                is_active=trainer_class.is_active,
                is_published=trainer_class.is_published,
            )
            return gym_class

        gym_class.name = trainer_class.name
        gym_class.class_type = class_type
        gym_class.level = level
        gym_class.instructor = instructor_name
        gym_class.trainer_profile = trainer_profile
        gym_class.duration_minutes = trainer_class.duration_minutes
        gym_class.capacity = trainer_class.max_participants
        gym_class.description = trainer_class.description
        gym_class.is_active = trainer_class.is_active
        gym_class.is_published = trainer_class.is_published
        gym_class.trainer_class = trainer_class
        gym_class.save()
        return gym_class

    @classmethod
    @transaction.atomic
    def sync_gym_schedule_to_trainer_schedule(cls, gym_schedule: GymSchedule) -> TrainerSchedule:
        trainer_profile = gym_schedule.trainer_profile
        if trainer_profile is None and gym_schedule.gym_class and gym_schedule.gym_class.trainer_profile:
            trainer_profile = gym_schedule.gym_class.trainer_profile
            gym_schedule.trainer_profile = trainer_profile
            gym_schedule.save(update_fields=['trainer_profile', 'updated_at'])

        if trainer_profile is None:
            raise ValueError('GymSchedule requires trainer_profile before sync.')

        trainer_class = None
        if gym_schedule.gym_class and gym_schedule.gym_class.trainer_class:
            trainer_class = gym_schedule.gym_class.trainer_class
        if trainer_class is None:
            trainer_class = (
                TrainerClass.objects.filter(trainer=trainer_profile, is_deleted=False)
                .order_by('id')
                .first()
            )
        if trainer_class is None:
            raise ValueError('GymSchedule requires a linked trainer class before sync.')

        trainer_schedule = gym_schedule.trainer_schedule
        payload = {
            'trainer_class': trainer_class,
            'trainer': trainer_profile,
            'start_time': gym_schedule.start_time,
            'end_time': gym_schedule.end_time,
            'is_active': gym_schedule.is_active,
            'is_published': gym_schedule.is_published,
        }

        if gym_schedule.recurrence_mode == 'weekly':
            payload['day_of_week'] = gym_schedule.day_of_week
            payload['scheduled_date'] = None
        else:
            payload['day_of_week'] = None
            payload['scheduled_date'] = gym_schedule.scheduled_date

        if trainer_schedule is None:
            trainer_schedule = TrainerSchedule.objects.create(**payload)
            gym_schedule.trainer_schedule = trainer_schedule
            gym_schedule.save(update_fields=['trainer_schedule', 'updated_at'])
            return trainer_schedule

        for key, value in payload.items():
            setattr(trainer_schedule, key, value)
        trainer_schedule.save()
        return trainer_schedule

    @classmethod
    @transaction.atomic
    def sync_trainer_schedule_to_gym_schedule(cls, trainer_schedule: TrainerSchedule) -> GymSchedule:
        trainer_class = trainer_schedule.trainer_class
        gym_class = getattr(trainer_class, 'gym_class', None)
        gym_schedule = getattr(trainer_schedule, 'gym_schedule', None)

        title = trainer_class.name
        class_type = gym_class.class_type if gym_class else (trainer_class.category or '')
        instructor = trainer_schedule.trainer.user.full_name

        if gym_schedule is None:
            recurrence_mode = 'weekly' if trainer_schedule.day_of_week else 'one_off'
            gym_schedule = GymSchedule.objects.create(
                gym_class=gym_class,
                trainer_profile=trainer_schedule.trainer,
                title=title,
                class_type=class_type,
                instructor=instructor,
                recurrence_mode=recurrence_mode,
                scheduled_date=trainer_schedule.scheduled_date,
                day_of_week=trainer_schedule.day_of_week or 'monday',
                start_time=trainer_schedule.start_time,
                end_time=trainer_schedule.end_time,
                capacity=trainer_class.max_participants,
                is_active=trainer_schedule.is_active,
                is_published=trainer_schedule.is_published,
            )
            trainer_schedule.gym_schedule = gym_schedule
            gym_schedule.trainer_schedule = trainer_schedule
            gym_schedule.save(update_fields=['trainer_schedule', 'updated_at'])
            return gym_schedule

        gym_schedule.gym_class = gym_class
        gym_schedule.trainer_profile = trainer_schedule.trainer
        gym_schedule.title = title
        gym_schedule.class_type = class_type
        gym_schedule.instructor = instructor
        gym_schedule.recurrence_mode = 'weekly' if trainer_schedule.day_of_week else 'one_off'
        gym_schedule.scheduled_date = trainer_schedule.scheduled_date
        if trainer_schedule.day_of_week:
            gym_schedule.day_of_week = trainer_schedule.day_of_week
        gym_schedule.start_time = trainer_schedule.start_time
        gym_schedule.end_time = trainer_schedule.end_time
        gym_schedule.capacity = trainer_class.max_participants
        gym_schedule.is_active = trainer_schedule.is_active
        gym_schedule.is_published = trainer_schedule.is_published
        gym_schedule.trainer_schedule = trainer_schedule
        gym_schedule.save()
        return gym_schedule

    @classmethod
    def delete_gym_schedule(cls, gym_schedule: GymSchedule) -> None:
        cls._assert_no_active_bookings(gym_schedule.trainer_schedule)
        if gym_schedule.trainer_schedule_id:
            gym_schedule.trainer_schedule.delete()
        gym_schedule.delete()

    @classmethod
    def delete_trainer_schedule(cls, trainer_schedule: TrainerSchedule) -> None:
        cls._assert_no_active_bookings(trainer_schedule)
        gym_schedule = getattr(trainer_schedule, 'gym_schedule', None)
        trainer_schedule.delete()
        if gym_schedule is not None:
            gym_schedule.delete()

    @staticmethod
    def _assert_no_active_bookings(trainer_schedule: TrainerSchedule | None) -> None:
        if trainer_schedule is None:
            return
        has_bookings = ScheduleBooking.objects.filter(
            schedule=trainer_schedule,
            is_deleted=False,
            status__in=['confirmed', 'waitlisted'],
        ).exists()
        if has_bookings:
            raise ValueError('Cannot delete schedule with active bookings.')
