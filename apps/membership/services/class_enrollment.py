from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, QuerySet
from django.utils import timezone

from apps.membership.models import ClassEnrollment, GymClass, GymSchedule, Member
from apps.membership.services.class_catalog import ClassCatalogService, MandatoryTrainerRequired
from apps.trainer.models import ScheduleBooking, TrainerSchedule


class ClassEnrollmentServiceError(Exception):
    """Base error for class enrollment operations."""


class CapacityExceeded(ClassEnrollmentServiceError):
    """Raised when class capacity would be exceeded."""


class ClassEnrollmentService:
    def __init__(self, *, user=None):
        self.user = user

    def _active_enrollment_count(self, gym_class: GymClass) -> int:
        return ClassEnrollment.objects.filter(
            gym_class=gym_class,
            status='active',
            is_deleted=False,
        ).count()

    def _get_gym_class(self, gym_class_id: int) -> GymClass:
        gym_class = (
            GymClass.objects.filter(pk=gym_class_id, is_deleted=False)
            .select_related('trainer_profile', 'trainer_class')
            .first()
        )
        if gym_class is None:
            raise ClassEnrollmentServiceError('Class not found.')
        return gym_class

    def _validate_members(self, member_ids: list[int]) -> list[Member]:
        members = list(
            Member.objects.filter(pk__in=member_ids, is_deleted=False, is_active=True)
        )
        if len(members) != len(set(member_ids)):
            raise ClassEnrollmentServiceError('One or more members were not found or are inactive.')
        return members

    def _future_trainer_schedules(self, gym_class: GymClass) -> QuerySet[TrainerSchedule]:
        trainer_class = gym_class.trainer_class
        if trainer_class is None:
            return TrainerSchedule.objects.none()

        today = timezone.now().date()
        return TrainerSchedule.objects.filter(
            trainer_class=trainer_class,
            is_deleted=False,
            is_cancelled=False,
        ).filter(
            Q(scheduled_date__gte=today) | Q(scheduled_date__isnull=True)
        )

    def _create_booking_for_schedule(
        self,
        schedule: TrainerSchedule,
        member: Member,
        *,
        source: str = 'admin_assigned',
    ) -> ScheduleBooking | None:
        if ScheduleBooking.objects.filter(
            schedule=schedule, member=member, is_deleted=False
        ).exclude(status='cancelled').exists():
            return None
        if schedule.is_full:
            return None
        try:
            booking = ScheduleBooking.objects.create(
                schedule=schedule,
                member=member,
                status='confirmed',
                source=source,
                created_by=self.user,
            )
        except IntegrityError:
            return None
        schedule.current_participants += 1
        schedule.is_full = schedule.current_participants >= schedule.trainer_class.max_participants
        schedule.save(update_fields=['current_participants', 'is_full'])
        return booking

    @transaction.atomic
    def enroll_members(
        self,
        gym_class: GymClass,
        member_ids: list[int],
        *,
        sync_future_sessions: bool = True,
        notify_channels: list[str] | None = None,
        tenant=None,
    ) -> list[ClassEnrollment]:
        gym_class = GymClass.objects.select_for_update().get(pk=gym_class.pk)
        members = self._validate_members(member_ids)
        active_count = self._active_enrollment_count(gym_class)
        new_count = 0
        for member_id in member_ids:
            if not ClassEnrollment.objects.filter(
                gym_class=gym_class,
                member_id=member_id,
                status='active',
                is_deleted=False,
            ).exists():
                new_count += 1
        if active_count + new_count > gym_class.capacity:
            raise CapacityExceeded(
                f'Class capacity is {gym_class.capacity}; cannot add {new_count} more members.'
            )

        enrollments: list[ClassEnrollment] = []
        notified_members: list[Member] = []
        for member in members:
            existing = ClassEnrollment.objects.filter(
                gym_class=gym_class,
                member=member,
                is_deleted=False,
            ).first()
            if existing:
                if existing.status == 'removed':
                    existing.status = 'active'
                    existing.source = 'admin'
                    existing.enrolled_by = self.user
                    existing.updated_by = self.user
                    existing.save(update_fields=['status', 'source', 'enrolled_by', 'updated_by', 'updated_at'])
                    enrollments.append(existing)
                    notified_members.append(member)
                else:
                    enrollments.append(existing)
                continue
            enrollment = ClassEnrollment.objects.create(
                gym_class=gym_class,
                member=member,
                status='active',
                source='admin',
                enrolled_by=self.user,
                created_by=self.user,
            )
            enrollments.append(enrollment)
            notified_members.append(member)

            if sync_future_sessions:
                for schedule in self._future_trainer_schedules(gym_class):
                    self._create_booking_for_schedule(schedule, member)

        if notify_channels and notified_members:
            from apps.membership.services.class_enrollment_notification import (
                dispatch_class_enrollment_notifications,
            )

            member_ids_to_notify = [member.pk for member in notified_members]
            channels = list(notify_channels)
            actor = self.user
            gym_class_id = gym_class.pk

            def _dispatch() -> None:
                refreshed_class = (
                    GymClass.objects.filter(pk=gym_class_id, is_deleted=False)
                    .select_related('trainer_profile__user')
                    .first()
                )
                if refreshed_class is None:
                    return
                members_to_notify = list(
                    Member.objects.filter(pk__in=member_ids_to_notify, is_deleted=False)
                )
                dispatch_class_enrollment_notifications(
                    refreshed_class,
                    members_to_notify,
                    channels,
                    actor=actor,
                    tenant=tenant,
                )

            transaction.on_commit(_dispatch)

        return enrollments

    @transaction.atomic
    def remove_members(
        self,
        gym_class: GymClass,
        member_ids: list[int],
        *,
        cancel_future_bookings: bool = True,
    ) -> int:
        removed = 0
        today = timezone.now().date()
        for enrollment in ClassEnrollment.objects.filter(
            gym_class=gym_class,
            member_id__in=member_ids,
            status='active',
            is_deleted=False,
        ).select_related('member'):
            enrollment.status = 'removed'
            enrollment.updated_by = self.user
            enrollment.save(update_fields=['status', 'updated_by', 'updated_at'])
            removed += 1

            if cancel_future_bookings and gym_class.trainer_class_id:
                future_bookings = ScheduleBooking.objects.filter(
                    member=enrollment.member,
                    schedule__trainer_class_id=gym_class.trainer_class_id,
                    is_deleted=False,
                    status__in=['confirmed', 'waitlisted'],
                ).filter(
                    Q(schedule__scheduled_date__gte=today) | Q(schedule__scheduled_date__isnull=True)
                ).select_related('schedule')
                for booking in future_bookings:
                    schedule = booking.schedule
                    booking.status = 'cancelled'
                    booking.updated_by = self.user
                    booking.save(update_fields=['status', 'updated_by', 'updated_at'])
                    schedule.current_participants = max(0, schedule.current_participants - 1)
                    schedule.is_full = False
                    schedule.save(update_fields=['current_participants', 'is_full'])

        return removed

    def list_enrolled_members(
        self,
        gym_class: GymClass,
        *,
        search: str | None = None,
        ordering: str | None = None,
    ) -> QuerySet[ClassEnrollment]:
        qs = ClassEnrollment.objects.filter(
            gym_class=gym_class,
            status='active',
            is_deleted=False,
        ).select_related('member', 'enrolled_by')
        if search:
            qs = qs.filter(
                Q(member__full_name__icontains=search)
                | Q(member__email__icontains=search)
                | Q(member__phone_number__icontains=search)
            )
        if ordering:
            qs = qs.order_by(ordering)
        else:
            qs = qs.order_by('-enrolled_at')
        return qs

    @transaction.atomic
    def assign_trainer(self, gym_class: GymClass, trainer_profile_id: int) -> GymClass:
        catalog = ClassCatalogService(user=self.user)
        return catalog.update_gym_class_from_admin(
            gym_class,
            {'trainer_profile_id': trainer_profile_id},
        )

    def list_class_schedules(self, gym_class: GymClass) -> QuerySet[GymSchedule]:
        return GymSchedule.objects.filter(
            gym_class=gym_class,
            is_deleted=False,
        ).select_related('trainer_profile__user', 'trainer_schedule').order_by('day_of_week', 'start_time')

    def get_detail_stats(self, gym_class: GymClass) -> dict[str, Any]:
        active_enrollments = self._active_enrollment_count(gym_class)
        schedule_count = GymSchedule.objects.filter(gym_class=gym_class, is_deleted=False).count()
        return {
            'active_enrollments': active_enrollments,
            'schedule_count': schedule_count,
            'capacity_remaining': max(0, gym_class.capacity - active_enrollments),
        }

    @transaction.atomic
    def assign_members_to_schedule(
        self,
        gym_schedule: GymSchedule,
        member_ids: list[int],
    ) -> list[ScheduleBooking]:
        if gym_schedule.trainer_schedule_id is None:
            raise ClassEnrollmentServiceError('Schedule is not synced to trainer workspace.')
        members = self._validate_members(member_ids)
        schedule = gym_schedule.trainer_schedule
        bookings: list[ScheduleBooking] = []
        for member in members:
            booking = self._create_booking_for_schedule(schedule, member)
            if booking:
                bookings.append(booking)
        return bookings
