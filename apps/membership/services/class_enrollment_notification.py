"""Email and in-app notifications when members are assigned to a class."""
from __future__ import annotations

import logging
from datetime import time

from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from apps.crm.email_delivery import resolve_tenant_mail_route
from apps.dashboard.models import GymProfile
from apps.identity.models import User
from apps.membership.models import GymClass, GymSchedule, Member
from apps.reminder.models import Notification
from apps.reminder.utils import create_notification

logger = logging.getLogger(__name__)

ACTIVE_CHANNELS = frozenset({"email", "in_app"})


def _filter_channels(channels: list[str] | None) -> list[str]:
    if not channels:
        return []
    return [channel for channel in channels if channel in ACTIVE_CHANNELS]


def _member_user(member: Member):
    if not member:
        return None
    qs = User.objects.filter(is_active=True)
    if member.email:
        user = qs.filter(email__iexact=member.email).first()
        if user:
            return user
    if member.phone_number:
        user = qs.filter(phone=member.phone_number).first()
        if user:
            return user
    return None


def _gym_name() -> str:
    profile = GymProfile.objects.first()
    return (profile.gym_name if profile and profile.gym_name else "Your Gym") or "Your Gym"


def _format_time_of_day(value: time | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        parts = value.split(":")
        if len(parts) < 2:
            return value
        hour = int(parts[0])
        minute = int(parts[1])
    else:
        hour = value.hour
        minute = value.minute
    suffix = "AM" if hour < 12 else "PM"
    hour_12 = hour % 12 or 12
    return f"{hour_12}:{minute:02d} {suffix}"


def _schedule_rows(gym_class: GymClass) -> list[dict[str, str]]:
    schedules = GymSchedule.objects.filter(
        gym_class=gym_class,
        is_deleted=False,
    ).order_by("scheduled_date", "day_of_week", "start_time")

    rows: list[dict[str, str]] = []
    for schedule in schedules:
        time_range = (
            f"{_format_time_of_day(schedule.start_time)} – "
            f"{_format_time_of_day(schedule.end_time)}"
        )
        if schedule.recurrence_mode == "one_off" and schedule.scheduled_date:
            when = f"{schedule.scheduled_date.strftime('%b %d, %Y')} · {time_range}"
        else:
            when = f"{schedule.get_day_of_week_display()} · {time_range}"
        rows.append({"title": schedule.title, "when": when})
    return rows


def _instructor_name(gym_class: GymClass) -> str:
    trainer_profile = gym_class.trainer_profile
    if trainer_profile and trainer_profile.user:
        return trainer_profile.user.full_name or gym_class.instructor or "TBA"
    return gym_class.instructor or "TBA"


def dispatch_class_enrollment_notifications(
    gym_class: GymClass,
    members: list[Member],
    channels: list[str] | None,
    *,
    actor=None,
    tenant=None,
) -> None:
    """Notify assigned members about class enrollment and schedules."""
    active = _filter_channels(channels)
    if not active or not members:
        return

    gym_name = _gym_name()
    actor_name = getattr(actor, "full_name", None) or getattr(actor, "email", "") or "Staff"
    instructor = _instructor_name(gym_class)
    schedule_rows = _schedule_rows(gym_class)
    class_type = gym_class.get_class_type_display()
    level = gym_class.get_level_display()

    for member in members:
        member_email = (member.email or "").strip()
        member_name = member.full_name or member_email or "Member"

        if "email" in active and member_email:
            try:
                context = {
                    "member_name": member_name,
                    "gym_name": gym_name,
                    "class_name": gym_class.name,
                    "class_type": class_type,
                    "class_level": level,
                    "instructor": instructor,
                    "duration_minutes": gym_class.duration_minutes,
                    "description": gym_class.description or "",
                    "schedules": schedule_rows,
                }
                html_body = render_to_string(
                    "membership/emails/class_enrollment_confirmation.html",
                    context,
                )
                schedule_lines = "\n".join(
                    f"- {row['title']}: {row['when']}" for row in schedule_rows
                ) or "- No schedules published yet."
                text_body = (
                    f"Hi {member_name},\n\n"
                    f"You have been enrolled in {gym_class.name} at {gym_name}.\n\n"
                    f"Instructor: {instructor}\n"
                    f"Type: {class_type}\n"
                    f"Level: {level}\n"
                    f"Duration: {gym_class.duration_minutes} minutes\n\n"
                    f"Schedules:\n{schedule_lines}\n\n"
                    f"Thank you,\n{gym_name}"
                )
                from_email, connection = resolve_tenant_mail_route(tenant)
                email = EmailMultiAlternatives(
                    subject=f"Class enrollment — {gym_class.name}",
                    body=text_body,
                    from_email=from_email,
                    to=[member_email],
                    connection=connection,
                )
                email.attach_alternative(html_body, "text/html")
                email.send(fail_silently=True)
            except Exception:
                logger.exception(
                    "Failed class enrollment email class_id=%s member_id=%s",
                    gym_class.id,
                    member.id,
                )

        if "in_app" in active:
            member_user = _member_user(member)
            if not member_user:
                continue
            schedule_summary = (
                f"{len(schedule_rows)} upcoming session(s)."
                if schedule_rows
                else "Schedules will be shared soon."
            )
            try:
                create_notification(
                    notification_type=Notification.CLASS_ENROLLMENT_CONFIRMED,
                    title=f"Enrolled in {gym_class.name}",
                    message=(
                        f"You were added to {gym_class.name} with {instructor}. "
                        f"{schedule_summary}"
                    ),
                    actor_name=actor_name,
                    recipient=member_user,
                    target_type="gym_class",
                    target_id=str(gym_class.id),
                    metadata={
                        "class_name": gym_class.name,
                        "instructor": instructor,
                        "schedule_count": len(schedule_rows),
                    },
                )
            except Exception:
                logger.exception(
                    "Failed class enrollment in-app notification class_id=%s member_id=%s",
                    gym_class.id,
                    member.id,
                )
