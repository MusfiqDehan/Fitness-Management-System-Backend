from __future__ import annotations

from datetime import datetime, time, timedelta

from django.utils import timezone

from apps.membership.models import Attendance, Member

DUPLICATE_PUNCH_WINDOW = timedelta(seconds=60)


def _local_day_bounds(day):
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(day, time.min), tz)
    end = timezone.make_aware(datetime.combine(day, time.max), tz)
    return start, end


def _has_check_in_on_date(member: Member, day) -> bool:
    start, end = _local_day_bounds(day)
    return Attendance.objects.filter(
        member=member,
        check_in_time__gte=start,
        check_in_time__lte=end,
    ).exists()


def apply_member_punch(
    member: Member,
    *,
    entry_method: str,
    device_id: str | None = None,
    device_uid: str = "",
    at=None,
) -> str | None:
    """Toggle member attendance session with duplicate debounce.

    Returns ``checked_in``, ``checked_out``, or ``None`` when ignored.

    Each member may have at most one check-in and one check-out per local
    calendar day (card and fingerprint share the same daily session).
    """
    now = at or timezone.now()
    punch_day = timezone.localtime(now).date()

    open_attendance = Attendance.objects.filter(
        member=member,
        check_out_time__isnull=True,
    ).first()
    if open_attendance:
        if now - open_attendance.check_in_time < DUPLICATE_PUNCH_WINDOW:
            return None
        open_attendance.check_out_time = now
        open_attendance.save(update_fields=["check_out_time"])
        return "checked_out"

    last_entry = Attendance.objects.filter(member=member).order_by("-check_in_time").first()
    if last_entry:
        last_action_time = last_entry.check_out_time or last_entry.check_in_time
        if now - last_action_time < DUPLICATE_PUNCH_WINDOW:
            return None

    if _has_check_in_on_date(member, punch_day):
        return None

    attendance = Attendance.objects.create(
        member=member,
        entry_method=entry_method,
        device_id=device_id,
        device_uid=device_uid or "",
    )
    # auto_now_add ignores an explicit check_in_time on create; align stored time with punch.
    Attendance.objects.filter(pk=attendance.pk).update(check_in_time=now)
    return "checked_in"
