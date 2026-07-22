"""Queue device credential deletes for expired members on scheduled cleanup slots."""
from __future__ import annotations

import calendar
import logging
from datetime import datetime
from typing import Any

from django.db import connection, transaction
from django.utils import timezone
from django_tenants.utils import get_public_schema_name, schema_context

from apps.attendance.models import DeviceUser
from apps.attendance.services.device_user_delete import DeviceUserDeleteService
from apps.dashboard.models import GymPreferences
from apps.membership.models import Member
from apps.tenancy.models import Tenant
from apps.tenancy.services import tenant_has_feature

logger = logging.getLogger(__name__)

SETTINGS_PREFERENCES_FEATURE = "settings.preferences"
# Only linked identities are on devices; unlink/pending/deleted are skipped.
DELETABLE_STATUSES = (DeviceUser.STATUS_LINKED,)


def add_one_calendar_month(dt: datetime) -> datetime:
    """Advance datetime by one calendar month, clamping day for shorter months."""
    year = dt.year + (1 if dt.month == 12 else 0)
    month = 1 if dt.month == 12 else dt.month + 1
    last_day = calendar.monthrange(year, month)[1]
    day = min(dt.day, last_day)
    return dt.replace(year=year, month=month, day=day)


def _member_still_expired(*, member_id: int, today) -> Member | None:
    """Re-check expiry under row lock to avoid deleting after a concurrent renewal."""
    member = (
        Member.objects.select_for_update()
        .filter(pk=member_id, is_deleted=False)
        .first()
    )
    if member is None:
        return None
    if not member.end_date or member.end_date >= today:
        return None
    return member


def _queue_deletes_for_expired_members(*, now: datetime) -> dict[str, int]:
    today = timezone.localtime(now).date() if timezone.is_aware(now) else now.date()
    queued = 0
    skipped = 0
    failed = 0

    expired_ids = list(
        Member.objects.filter(is_deleted=False, end_date__lt=today).values_list("id", flat=True)
    )
    for member_id in expired_ids:
        with transaction.atomic():
            member = _member_still_expired(member_id=member_id, today=today)
            if member is None:
                skipped += 1
                continue

            device_users = list(
                DeviceUser.objects.select_related("access_device").filter(
                    member_id=member.id,
                    status__in=DELETABLE_STATUSES,
                )
            )
            for device_user in device_users:
                device = device_user.access_device
                try:
                    DeviceUserDeleteService.queue_delete(device_user=device_user, device=device)
                    queued += 1
                except ValueError as exc:
                    skipped += 1
                    logger.info(
                        "Skip credential delete member=%s device_user=%s: %s",
                        member.id,
                        device_user.id,
                        exc,
                    )
                except Exception:
                    failed += 1
                    logger.exception(
                        "Failed credential delete member=%s device_user=%s",
                        member.id,
                        device_user.id,
                    )
    return {"queued": queued, "skipped": skipped, "failed": failed}


def _current_tenant_has_preferences_feature() -> bool:
    schema_name = getattr(connection, "schema_name", None)
    if not schema_name or schema_name == get_public_schema_name():
        return False
    tenant = Tenant.objects.filter(schema_name=schema_name).only("id", "schema_name").first()
    if tenant is None:
        return False
    return tenant_has_feature(tenant, SETTINGS_PREFERENCES_FEATURE)


def process_tenant_cleanup_slots(*, now: datetime | None = None) -> dict[str, Any]:
    """Process due cleanup slots for the current tenant schema.

    Replay safety: due slots are advanced under ``select_for_update`` *before*
    any device deletes are queued, so a crash/retry cannot re-fire the same slot.
    When both slots are due, deletes run once (not per slot).
    """
    now = now or timezone.now()

    if not _current_tenant_has_preferences_feature():
        return {"acted": False, "reason": "feature_disabled", "slots": []}

    due_slots: list[str] = []
    slot_meta: list[dict[str, str]] = []

    with transaction.atomic():
        prefs = (
            GymPreferences.objects.select_for_update()
            .filter(pk=1)
            .first()
        )
        if prefs is None:
            prefs, _ = GymPreferences.objects.get_or_create(pk=1)
            prefs = GymPreferences.objects.select_for_update().get(pk=1)

        if not prefs.payment_auto_delete_credentials_enabled:
            return {"acted": False, "reason": "disabled", "slots": []}

        update_fields: list[str] = []
        for field_name in ("payment_cleanup_run_at_1", "payment_cleanup_run_at_2"):
            run_at = getattr(prefs, field_name)
            if run_at is None:
                continue
            if timezone.is_naive(run_at):
                run_at = timezone.make_aware(run_at, timezone.get_current_timezone())
            if run_at > now:
                continue

            next_run = add_one_calendar_month(run_at)
            while next_run <= now:
                next_run = add_one_calendar_month(next_run)
            setattr(prefs, field_name, next_run)
            update_fields.append(field_name)
            due_slots.append(field_name)
            slot_meta.append(
                {
                    "slot": field_name,
                    "ran_at": run_at.isoformat(),
                    "next_run_at": next_run.isoformat(),
                }
            )

        if not update_fields:
            return {"acted": False, "slots": []}

        update_fields.append("updated_at")
        prefs.save(update_fields=update_fields)

    # Queue once after slots are committed forward (job only queues; ACK handles retries).
    delete_stats = _queue_deletes_for_expired_members(now=now)
    return {
        "acted": True,
        "slots": [{**meta, **delete_stats} for meta in slot_meta],
    }


def run_expired_member_credential_cleanup(*, now: datetime | None = None) -> dict[str, Any]:
    """Iterate tenants and process due Payment Configurations cleanup slots."""
    now = now or timezone.now()
    tenants_processed = 0
    tenants_acted = 0
    tenant_results: list[dict[str, Any]] = []

    tenants = (
        Tenant.objects.filter(is_enabled=True)
        .exclude(schema_name=get_public_schema_name())
        .only("id", "schema_name")
    )
    for tenant in tenants:
        if not tenant_has_feature(tenant, SETTINGS_PREFERENCES_FEATURE):
            continue
        tenants_processed += 1
        with schema_context(tenant.schema_name):
            result = process_tenant_cleanup_slots(now=now)
        if result.get("acted"):
            tenants_acted += 1
        tenant_results.append({"schema": tenant.schema_name, **result})

    return {
        "tenants_processed": tenants_processed,
        "tenants_acted": tenants_acted,
        "results": tenant_results,
    }
