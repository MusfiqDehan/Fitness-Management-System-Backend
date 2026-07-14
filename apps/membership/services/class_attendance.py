from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from apps.membership.models import Attendance
from apps.trainer.models import ScheduleBooking, TrainerSchedule

GRACE_BEFORE_MINUTES = getattr(settings, 'CLASS_ATTENDANCE_GRACE_BEFORE_MINUTES', 15)
GRACE_AFTER_MINUTES = getattr(settings, 'CLASS_ATTENDANCE_GRACE_AFTER_MINUTES', 10)

WEEKDAY_TO_INDEX = {
    'monday': 0,
    'tuesday': 1,
    'wednesday': 2,
    'thursday': 3,
    'friday': 4,
    'saturday': 5,
    'sunday': 6,
}

VALID_PUNCTUALITY_VALUES = frozenset({'pending', 'on_time', 'late', 'absent'})


class ClassAttendanceServiceError(Exception):
    """Base error for class attendance operations."""


class InvalidPunctualityValue(ClassAttendanceServiceError):
    """Raised when an unsupported punctuality value is supplied."""


def _combine_date_time(session_date: date, session_time: time) -> datetime:
    tz = timezone.get_current_timezone()
    naive = datetime.combine(session_date, session_time)
    return timezone.make_aware(naive, tz) if timezone.is_naive(naive) else naive


def resolve_session_date(schedule: TrainerSchedule, reference: date | None = None) -> date | None:
    """Resolve the calendar date for a trainer schedule slot."""
    if schedule.scheduled_date:
        return schedule.scheduled_date
    if not schedule.day_of_week:
        return reference or timezone.now().date()
    ref = reference or timezone.now().date()
    target_idx = WEEKDAY_TO_INDEX.get(schedule.day_of_week)
    if target_idx is None:
        return ref
    current_idx = ref.weekday()
    days_ahead = (target_idx - current_idx) % 7
    return ref + timedelta(days=days_ahead)


def resolve_session_window(
    schedule: TrainerSchedule,
    reference: date | None = None,
) -> tuple[datetime, datetime] | None:
    session_date = resolve_session_date(schedule, reference)
    if session_date is None:
        return None
    start = _combine_date_time(session_date, schedule.start_time)
    end = _combine_date_time(session_date, schedule.end_time)
    return start, end


class ClassAttendanceService:
    @classmethod
    def compute_punctuality(
        cls,
        booking: ScheduleBooking,
        *,
        reference: date | None = None,
    ) -> dict[str, Any]:
        schedule = booking.schedule
        if booking.punctuality_override:
            window = resolve_session_window(schedule, reference)
            check_in = booking.check_in_time
            if check_in is None and window is not None:
                check_in = cls._find_door_check_in(booking, window)
            return {
                'punctuality': booking.punctuality_override,
                'punctuality_source': 'admin_override',
                'check_in_display': check_in,
                'entry_method': cls._entry_method_for_check_in(booking, check_in),
                'punctuality_override': booking.punctuality_override,
            }

        window = resolve_session_window(schedule, reference)
        now = timezone.now()

        if booking.status == 'cancelled':
            return {
                'punctuality': 'pending',
                'punctuality_source': 'none',
                'check_in_display': None,
                'entry_method': None,
                'punctuality_override': booking.punctuality_override,
            }

        check_in = booking.check_in_time
        punctuality_source = 'none'

        if check_in is None:
            door_time = cls._find_door_check_in(booking, window)
            if door_time:
                check_in = door_time
                punctuality_source = 'door'

        if window is None:
            return {
                'punctuality': 'pending',
                'punctuality_source': punctuality_source,
                'check_in_display': check_in,
                'entry_method': cls._entry_method_for_check_in(booking, check_in),
                'punctuality_override': booking.punctuality_override,
            }

        start, end = window
        grace_start = start - timedelta(minutes=GRACE_BEFORE_MINUTES)
        grace_end = end + timedelta(minutes=GRACE_AFTER_MINUTES)

        if check_in:
            if booking.check_in_time and not punctuality_source:
                punctuality_source = 'manual'
            if check_in <= end and check_in >= grace_start:
                if check_in <= start:
                    punctuality = 'on_time'
                else:
                    punctuality = 'late'
            elif check_in < grace_start:
                punctuality = 'on_time'
            else:
                punctuality = 'late'
            return {
                'punctuality': punctuality,
                'punctuality_source': punctuality_source,
                'check_in_display': check_in,
                'entry_method': cls._entry_method_for_check_in(booking, check_in),
                'punctuality_override': booking.punctuality_override,
            }

        if now > grace_end:
            return {
                'punctuality': 'absent',
                'punctuality_source': 'none',
                'check_in_display': None,
                'entry_method': None,
                'punctuality_override': booking.punctuality_override,
            }

        return {
            'punctuality': 'pending',
            'punctuality_source': 'none',
            'check_in_display': None,
            'entry_method': None,
            'punctuality_override': booking.punctuality_override,
        }

    @classmethod
    def set_punctuality_override(
        cls,
        booking: ScheduleBooking,
        punctuality: str | None,
        *,
        user=None,
    ) -> dict[str, Any]:
        if punctuality is not None and punctuality not in VALID_PUNCTUALITY_VALUES:
            raise InvalidPunctualityValue(
                f'Invalid punctuality value. Allowed: {", ".join(sorted(VALID_PUNCTUALITY_VALUES))}.'
            )

        booking.punctuality_override = punctuality or None
        update_fields = ['punctuality_override', 'updated_at']

        if punctuality == 'absent' and booking.status in {'confirmed', 'waitlisted', 'attended'}:
            booking.status = 'no_show'
            update_fields.append('status')
        elif punctuality in {'on_time', 'late'} and booking.status in {'confirmed', 'waitlisted', 'no_show'}:
            booking.status = 'attended'
            update_fields.append('status')
        elif punctuality == 'pending' and booking.status == 'no_show':
            booking.status = 'confirmed'
            update_fields.append('status')

        if user is not None:
            booking.updated_by = user
            update_fields.append('updated_by')

        booking.save(update_fields=list(dict.fromkeys(update_fields)))
        session_date = resolve_session_date(booking.schedule)
        return cls.compute_punctuality(booking, reference=session_date)

    @classmethod
    def get_class_booking(cls, gym_class, booking_id: int) -> ScheduleBooking | None:
        trainer_class_id = gym_class.trainer_class_id
        if not trainer_class_id:
            return None
        return (
            ScheduleBooking.objects.filter(
                pk=booking_id,
                schedule__trainer_class_id=trainer_class_id,
                is_deleted=False,
            )
            .exclude(status='cancelled')
            .select_related('member', 'schedule__trainer_class', 'schedule__trainer__user')
            .first()
        )

    @classmethod
    def _entry_method_for_check_in(
        cls,
        booking: ScheduleBooking,
        check_in: datetime | None,
    ) -> str | None:
        if check_in is None:
            return None
        if booking.check_in_time and check_in == booking.check_in_time:
            return 'manual'
        attendance = (
            Attendance.objects.filter(
                member=booking.member,
                check_in_time__gte=check_in - timedelta(minutes=2),
                check_in_time__lte=check_in + timedelta(minutes=2),
            )
            .order_by('check_in_time')
            .first()
        )
        if attendance:
            return attendance.entry_method
        return 'manual'

    @classmethod
    def _find_door_check_in(
        cls,
        booking: ScheduleBooking,
        window: tuple[datetime, datetime] | None,
    ) -> datetime | None:
        if window is None:
            return None
        start, end = window
        grace_start = start - timedelta(minutes=GRACE_BEFORE_MINUTES)
        grace_end = end + timedelta(minutes=GRACE_AFTER_MINUTES)
        attendance = (
            Attendance.objects.filter(
                member=booking.member,
                check_in_time__gte=grace_start,
                check_in_time__lte=grace_end,
                is_deleted=False,
            )
            .order_by('check_in_time')
            .first()
        )
        return attendance.check_in_time if attendance else None

    @classmethod
    def try_match_member_check_in(cls, member, check_in_time: datetime) -> int:
        """Match a door check-in to today's class bookings; auto-mark attended."""
        today = check_in_time.date()
        bookings = ScheduleBooking.objects.filter(
            member=member,
            is_deleted=False,
            status__in=['confirmed', 'waitlisted'],
        ).select_related('schedule__trainer_class')

        matched = 0
        for booking in bookings:
            window = resolve_session_window(booking.schedule, today)
            if window is None:
                continue
            start, end = window
            grace_start = start - timedelta(minutes=GRACE_BEFORE_MINUTES)
            grace_end = end + timedelta(minutes=GRACE_AFTER_MINUTES)
            if grace_start <= check_in_time <= grace_end:
                if booking.check_in_time is None:
                    booking.check_in_time = check_in_time
                    booking.status = 'attended'
                    booking.save(update_fields=['check_in_time', 'status', 'updated_at'])
                    matched += 1
        return matched

    @classmethod
    def enrich_booking(cls, booking: ScheduleBooking) -> dict[str, Any]:
        data = cls.compute_punctuality(booking)
        return {
            'source': booking.source,
            'punctuality': data['punctuality'],
            'punctuality_source': data['punctuality_source'],
            'check_in_display': data['check_in_display'],
            'entry_method': data['entry_method'],
        }

    @classmethod
    def list_class_attendance(
        cls,
        gym_class,
        *,
        search: str | None = None,
    ):
        from apps.trainer.models import ScheduleBooking as SB

        trainer_class_id = gym_class.trainer_class_id
        if not trainer_class_id:
            return []

        qs = SB.objects.filter(
            schedule__trainer_class_id=trainer_class_id,
            is_deleted=False,
        ).exclude(status='cancelled').select_related(
            'member', 'schedule__trainer_class', 'schedule__trainer__user'
        )
        if search:
            qs = qs.filter(
                Q(member__full_name__icontains=search)
                | Q(member__email__icontains=search)
            )
        results = []
        for booking in qs.order_by('-schedule__scheduled_date', '-schedule__start_time'):
            punct = cls.compute_punctuality(booking)
            schedule = booking.schedule
            session_date = resolve_session_date(schedule)
            results.append({
                'booking_id': booking.id,
                'member_id': booking.member_id,
                'member_name': booking.member.full_name,
                'session_date': session_date,
                'start_time': schedule.start_time,
                'end_time': schedule.end_time,
                'status': booking.status,
                'source': booking.source,
                'punctuality_override': booking.punctuality_override,
                **punct,
            })
        return results

    @classmethod
    def list_member_class_attendance(
        cls,
        member,
        *,
        day: str | None = None,
        month: int | None = None,
        year: int | None = None,
    ):
        qs = ScheduleBooking.objects.filter(
            member=member,
            is_deleted=False,
        ).exclude(status='cancelled').select_related(
            'schedule__trainer_class', 'schedule__trainer__user'
        )

        results = []
        for booking in qs.order_by('-schedule__scheduled_date', '-schedule__start_time'):
            schedule = booking.schedule
            session_date = resolve_session_date(schedule)
            if session_date is None:
                continue
            if day:
                if str(session_date) != day:
                    continue
            elif month and year:
                if session_date.month != month or session_date.year != year:
                    continue
            elif year:
                if session_date.year != year:
                    continue

            punct = cls.compute_punctuality(booking, reference=session_date)
            results.append({
                'booking_id': booking.id,
                'class_name': schedule.trainer_class.name,
                'session_date': session_date,
                'start_time': schedule.start_time,
                'end_time': schedule.end_time,
                'status': booking.status,
                'source': booking.source,
                **punct,
            })
        return results
