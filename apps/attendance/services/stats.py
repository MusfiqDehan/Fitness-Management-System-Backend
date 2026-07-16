from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta

from django.db.models import Count, Max, Q
from django.db.models.functions import TruncDate, TruncHour
from django.utils import timezone

from apps.membership.models import Attendance, Member
from utils.tenancy_helpers import scope_queryset_by_branch_access

HOURLY_RANGES = {"today", "yesterday", "last_7_days"}
HEATMAP_RANGES = {"this_year", "this_month", "this_week"}
STREAK_RANGES = {"this_year", "this_month"}
INACTIVE_DAYS_THRESHOLD = 7
TOP_N = 5


def _hour_label(hour: int) -> str:
    if hour == 0:
        return "12AM"
    if hour < 12:
        return f"{hour}AM"
    if hour == 12:
        return "12PM"
    return f"{hour - 12}PM"


def _membership_label(member: Member) -> str:
    if member.membership_type == "package" and member.member_package_id:
        return member.member_package.name
    return "Monthly"


def _scoped_attendance(user, *, branch_filter_id=None, device_sn: str | None = None):
    queryset = Attendance.objects.select_related("member", "member__member_package")
    queryset = scope_queryset_by_branch_access(
        queryset,
        user,
        branch_field="member__branch_id",
        branch_filter_id=branch_filter_id,
    )
    if device_sn:
        queryset = queryset.filter(device_id=device_sn)
    return queryset


def _scoped_members(user, *, branch_filter_id=None):
    queryset = Member.objects.filter(is_deleted=False).select_related("member_package")
    return scope_queryset_by_branch_access(
        queryset,
        user,
        branch_field="branch_id",
        branch_filter_id=branch_filter_id,
    )


def _hourly_window(hourly_range: str, now: datetime) -> tuple[datetime, datetime, str]:
    local_now = timezone.localtime(now)
    today = local_now.date()
    if hourly_range == "yesterday":
        day = today - timedelta(days=1)
        start = timezone.make_aware(datetime.combine(day, time.min), timezone.get_current_timezone())
        end = timezone.make_aware(datetime.combine(day, time.max), timezone.get_current_timezone())
        return start, end, hourly_range
    if hourly_range == "last_7_days":
        start_day = today - timedelta(days=6)
        start = timezone.make_aware(datetime.combine(start_day, time.min), timezone.get_current_timezone())
        return start, local_now, hourly_range
    start = timezone.make_aware(datetime.combine(today, time.min), timezone.get_current_timezone())
    return start, local_now, "today"


def build_hourly_foot_traffic(user, *, branch_filter_id=None, device_sn=None, hourly_range="today"):
    hourly_range = hourly_range if hourly_range in HOURLY_RANGES else "today"
    now = timezone.now()
    start, end, resolved_range = _hourly_window(hourly_range, now)
    queryset = _scoped_attendance(user, branch_filter_id=branch_filter_id, device_sn=device_sn)
    queryset = queryset.filter(check_in_time__gte=start, check_in_time__lte=end)

    if hourly_range == "last_7_days":
        counts: dict[int, int] = defaultdict(int)
        for row in queryset.values_list("check_in_time", flat=True):
            local = timezone.localtime(row)
            counts[local.hour] += 1
        buckets = [{"hour": hour, "label": _hour_label(hour), "count": counts.get(hour, 0)} for hour in range(24)]
    else:
        counts = {hour: 0 for hour in range(24)}
        for row in queryset.annotate(hour=TruncHour("check_in_time")).values("hour").annotate(count=Count("id")):
            if row["hour"]:
                counts[timezone.localtime(row["hour"]).hour] = row["count"]
        buckets = [{"hour": hour, "label": _hour_label(hour), "count": counts[hour]} for hour in range(24)]

    peak_hour = max(buckets, key=lambda item: item["count"])["hour"] if buckets else 0
    return {
        "range": resolved_range,
        "buckets": buckets,
        "peak_hour": peak_hour,
        "peak_count": max((item["count"] for item in buckets), default=0),
    }


def _heatmap_window(heatmap_range: str, now: datetime) -> tuple[date, date, str]:
    local_today = timezone.localdate(now)
    if heatmap_range == "this_week":
        week_start = local_today - timedelta(days=(local_today.weekday() + 1) % 7)
        return week_start, local_today, "this_week"
    if heatmap_range == "this_month":
        return local_today.replace(day=1), local_today, "this_month"
    return local_today.replace(month=1, day=1), local_today, "this_year"


def build_visit_heatmap(user, *, branch_filter_id=None, device_sn=None, heatmap_range="this_year"):
    heatmap_range = heatmap_range if heatmap_range in HEATMAP_RANGES else "this_year"
    now = timezone.now()
    start_date, end_date, resolved_range = _heatmap_window(heatmap_range, now)
    tz = timezone.get_current_timezone()
    start_dt = timezone.make_aware(datetime.combine(start_date, time.min), tz)
    end_dt = timezone.make_aware(datetime.combine(end_date, time.max), tz)

    queryset = _scoped_attendance(user, branch_filter_id=branch_filter_id, device_sn=device_sn)
    queryset = queryset.filter(check_in_time__gte=start_dt, check_in_time__lte=end_dt)

    day_counts: dict[date, int] = defaultdict(int)
    for row in queryset.annotate(day=TruncDate("check_in_time")).values("day").annotate(count=Count("id")):
        if row["day"]:
            day_counts[row["day"]] = row["count"]

    cells = []
    cursor = start_date
    while cursor <= end_date:
        cells.append({"date": cursor.isoformat(), "count": day_counts.get(cursor, 0)})
        cursor += timedelta(days=1)

    max_count = max((cell["count"] for cell in cells), default=0)
    return {"range": resolved_range, "cells": cells, "max_count": max_count}


def _longest_streak(visit_dates: list[date]) -> int:
    if not visit_dates:
        return 0
    unique_dates = sorted(set(visit_dates))
    best = current = 1
    for index in range(1, len(unique_dates)):
        if unique_dates[index] - unique_dates[index - 1] == timedelta(days=1):
            current += 1
        else:
            best = max(best, current)
            current = 1
    return max(best, current)


def _streak_window(streak_range: str, now: datetime) -> tuple[date, date, str]:
    local_today = timezone.localdate(now)
    if streak_range == "this_month":
        return local_today.replace(day=1), local_today, "this_month"
    return local_today.replace(month=1, day=1), local_today, "this_year"


def build_top_streaks(user, *, branch_filter_id=None, device_sn=None, streak_range="this_year"):
    streak_range = streak_range if streak_range in STREAK_RANGES else "this_year"
    now = timezone.now()
    start_date, end_date, resolved_range = _streak_window(streak_range, now)
    tz = timezone.get_current_timezone()
    start_dt = timezone.make_aware(datetime.combine(start_date, time.min), tz)
    end_dt = timezone.make_aware(datetime.combine(end_date, time.max), tz)

    queryset = _scoped_attendance(user, branch_filter_id=branch_filter_id, device_sn=device_sn)
    queryset = queryset.filter(check_in_time__gte=start_dt, check_in_time__lte=end_dt)

    visits_by_member: dict[int, list[date]] = defaultdict(list)
    member_map: dict[int, Member] = {}
    for attendance in queryset.select_related("member", "member__member_package"):
        visit_day = timezone.localtime(attendance.check_in_time).date()
        visits_by_member[attendance.member_id].append(visit_day)
        member_map[attendance.member_id] = attendance.member

    ranked = []
    for member_id, visit_dates in visits_by_member.items():
        member = member_map[member_id]
        ranked.append(
            {
                "member_id": member.id,
                "member_name": member.full_name,
                "membership_label": _membership_label(member),
                "streak_days": _longest_streak(visit_dates),
            }
        )
    ranked.sort(key=lambda row: (-row["streak_days"], row["member_name"]))
    return {"range": resolved_range, "results": ranked[:TOP_N]}


def build_inactive_members(user, *, branch_filter_id=None, device_sn=None):
    now = timezone.now()
    cutoff = now - timedelta(days=INACTIVE_DAYS_THRESHOLD)
    members = _scoped_members(user, branch_filter_id=branch_filter_id).filter(is_active=True)

    attendance_qs = _scoped_attendance(user, branch_filter_id=branch_filter_id, device_sn=device_sn)
    last_visits = (
        attendance_qs.values("member_id")
        .annotate(last_check_in=Max("check_in_time"))
        .filter(last_check_in__lt=cutoff)
    )
    last_visit_map = {row["member_id"]: row["last_check_in"] for row in last_visits}

    results = []
    for member in members.filter(id__in=last_visit_map.keys()):
        last_check_in = last_visit_map[member.id]
        days_since = (timezone.localdate(now) - timezone.localtime(last_check_in).date()).days
        results.append(
            {
                "member_id": member.id,
                "member_name": member.full_name,
                "membership_label": _membership_label(member),
                "days_since_visit": days_since,
                "last_check_in": last_check_in,
            }
        )

    results.sort(key=lambda row: (-row["days_since_visit"], row["member_name"]))
    trimmed = results[:TOP_N]
    for row in trimmed:
        row.pop("last_check_in", None)
    return {"days_threshold": INACTIVE_DAYS_THRESHOLD, "results": trimmed}


class AttendanceStatsService:
    @classmethod
    def build_payload(
        cls,
        user,
        *,
        branch_filter_id=None,
        device_sn=None,
        hourly_range="today",
        heatmap_range="this_year",
        streak_range="this_year",
    ) -> dict:
        return {
            "hourly_foot_traffic": build_hourly_foot_traffic(
                user,
                branch_filter_id=branch_filter_id,
                device_sn=device_sn,
                hourly_range=hourly_range,
            ),
            "visit_heatmap": build_visit_heatmap(
                user,
                branch_filter_id=branch_filter_id,
                device_sn=device_sn,
                heatmap_range=heatmap_range,
            ),
            "top_streaks": build_top_streaks(
                user,
                branch_filter_id=branch_filter_id,
                device_sn=device_sn,
                streak_range=streak_range,
            ),
            "inactive_members": build_inactive_members(
                user,
                branch_filter_id=branch_filter_id,
                device_sn=device_sn,
            ),
        }
