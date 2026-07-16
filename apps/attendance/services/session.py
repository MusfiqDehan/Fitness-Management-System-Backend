from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from apps.membership.models import Attendance, Member

DUPLICATE_PUNCH_WINDOW = timedelta(seconds=60)


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
    """
    now = at or timezone.now()

    open_attendance = Attendance.objects.filter(
        member=member,
        check_out_time__isnull=True,
    ).first()
    if open_attendance:
        if at - open_attendance.check_in_time < DUPLICATE_PUNCH_WINDOW:
            return None
        open_attendance.check_out_time = at
        open_attendance.save(update_fields=["check_out_time"])
        return "checked_out"

    last_entry = Attendance.objects.filter(member=member).order_by("-check_in_time").first()
    if last_entry:
        last_action_time = last_entry.check_out_time or last_entry.check_in_time
        if at - last_action_time < DUPLICATE_PUNCH_WINDOW:
            return None

    Attendance.objects.create(
        member=member,
        entry_method=entry_method,
        device_id=device_id,
        device_uid=device_uid or "",
        check_in_time=at,
    )
    return "checked_in"
