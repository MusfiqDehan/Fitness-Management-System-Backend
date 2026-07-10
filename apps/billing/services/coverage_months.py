"""Helpers for payment coverage months (YYYY-MM)."""
from __future__ import annotations

import calendar
import re
from datetime import datetime
from typing import Any

from django.db.models import Func, IntegerField, Q, QuerySet, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework.exceptions import ValidationError

_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


class JsonbArrayLength(Func):
    function = "jsonb_array_length"
    arity = 1
    output_field = IntegerField()


def format_coverage_months_label(months: list[str] | None) -> str:
    """Human-readable coverage list, e.g. 'Jul 2026, Sep 2026'."""
    if not months:
        return ""
    labels: list[str] = []
    for raw in months:
        match = _MONTH_RE.match(str(raw).strip())
        if not match:
            labels.append(str(raw))
            continue
        year, month = int(match.group(1)), int(match.group(2))
        if 1 <= month <= 12:
            labels.append(f"{calendar.month_abbr[month]} {year}")
        else:
            labels.append(str(raw))
    return ", ".join(labels)


def month_key_from_datetime(value: datetime | None) -> str:
    dt = value or timezone.now()
    if timezone.is_aware(dt):
        dt = timezone.localtime(dt)
    return f"{dt.year:04d}-{dt.month:02d}"


def normalize_coverage_months(
    months: list[Any] | None,
    *,
    payment_date: datetime | None = None,
    required: bool = True,
) -> list[str]:
    """Validate, unique-sort, and optionally default coverage months."""
    if months is None or (isinstance(months, list) and len(months) == 0):
        if required:
            return [month_key_from_datetime(payment_date)]
        return []

    if not isinstance(months, list):
        raise ValidationError({"coverage_months": "Must be a list of YYYY-MM strings."})

    normalized: list[str] = []
    seen: set[str] = set()
    errors: list[str] = []
    for item in months:
        raw = str(item).strip() if item is not None else ""
        match = _MONTH_RE.match(raw)
        if not match:
            errors.append(f"Invalid month '{item}'. Use YYYY-MM.")
            continue
        month = int(match.group(2))
        if month < 1 or month > 12:
            errors.append(f"Invalid month '{raw}'. Month must be 01-12.")
            continue
        if raw not in seen:
            seen.add(raw)
            normalized.append(raw)

    if errors:
        raise ValidationError({"coverage_months": errors})
    if required and not normalized:
        raise ValidationError({"coverage_months": "Select at least one coverage month."})
    return sorted(normalized)


def apply_year_month_and_multi_month_filters(queryset: QuerySet, params) -> QuerySet:
    """Apply year/month (payment_date OR coverage) and multi_month filters."""
    year = params.get("year")
    month = params.get("month")
    multi_month = params.get("multi_month")

    if year and month:
        try:
            y = int(year)
            m = int(month)
        except (TypeError, ValueError) as exc:
            raise ValidationError({"year": "Invalid year/month."}) from exc
        if m < 1 or m > 12:
            raise ValidationError({"month": "Month must be 1-12."})
        key = f"{y:04d}-{m:02d}"
        queryset = queryset.filter(
            Q(payment_date__year=y, payment_date__month=m)
            | Q(coverage_months__contains=[key])
        )

    if str(multi_month).lower() in {"1", "true", "yes"}:
        queryset = queryset.annotate(
            _cov_len=Coalesce(JsonbArrayLength("coverage_months"), Value(0))
        ).filter(_cov_len__gt=1)

    return queryset
