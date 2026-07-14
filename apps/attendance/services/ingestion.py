from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import logging
import re

from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from apps.membership.models import Attendance, Member
from apps.attendance.models import AccessDevice, AttendanceIngestEvent, DeviceUser
from apps.attendance.services.enrollment import FingerprintEnrollmentService
from apps.attendance.services.realtime import publish_attendance_event

logger = logging.getLogger(__name__)


@dataclass
class ParsedEvent:
    event_type: str
    device_uid: str
    event_time: datetime | None
    raw_line: str
    name: str | None = None


class ADMSIngestionService:
    @staticmethod
    def process(device: AccessDevice, raw_body: str, table_hint: str | None = None) -> dict:
        events = ADMSIngestionService._parse_body(raw_body or "", table_hint=table_hint)
        logger.debug("[INGESTION] SN=%s parsed %d events from body", device.device_sn, len(events))
        handled = 0
        skipped = 0

        for event in events:
            logger.debug("[INGESTION] SN=%s event type=%s uid=%s time=%s",
                         device.device_sn, event.event_type, event.device_uid, event.event_time)
            if ADMSIngestionService._is_duplicate(device, event):
                logger.debug("[INGESTION] SN=%s DUPLICATE type=%s uid=%s", device.device_sn, event.event_type, event.device_uid)
                skipped += 1
                continue

            if event.event_type == "ATTLOG":
                ADMSIngestionService._handle_attlog(device, event)
            elif event.event_type in {"USERINFO", "FP", "OPERLOG"}:
                ADMSIngestionService._handle_device_user(device, event)
                if event.event_type == "FP":
                    FingerprintEnrollmentService.handle_fingerprint_ingested(
                        device=device,
                        device_uid=event.device_uid,
                    )

            handled += 1
            logger.info("[INGESTION] SN=%s handled type=%s uid=%s name=%s",
                        device.device_sn, event.event_type, event.device_uid, event.name)

        return {
            "handled": handled,
            "skipped": skipped,
            "total": len(events),
        }

    @staticmethod
    def _parse_body(body: str, table_hint: str | None = None) -> list[ParsedEvent]:
        current_table = (table_hint or "").strip().upper()
        out: list[ParsedEvent] = []

        for raw in body.splitlines():
            line = (raw or "").strip()
            if not line:
                continue

            lower = line.lower()
            if lower.startswith("table="):
                current_table = line.split("=", 1)[1].strip().upper()
                continue

            if current_table == "ATTLOG":
                parts = [p.strip() for p in line.split("\t") if p.strip()]
                if len(parts) < 2:
                    continue
                uid = parts[0]
                dt = ADMSIngestionService._parse_datetime(parts[1])
                out.append(ParsedEvent("ATTLOG", uid, dt, line))
                continue

            if current_table in {"USERINFO", "FP", "OPERLOG"}:
                uid = ADMSIngestionService._extract_pin(line)
                if not uid:
                    uid_match = re.search(r"^(\d+)\t", line)
                    if uid_match:
                        uid = uid_match.group(1)
                if not uid:
                    continue
                name = ADMSIngestionService._extract_kv_field(line, "Name")
                out.append(ParsedEvent(current_table, uid, None, line, name=name))

        return out

    @staticmethod
    def _extract_pin(line: str) -> str:
        match = re.search(r"(?:^|\s)PIN=([^\s]+)", line)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _extract_kv_field(line: str, key: str) -> str | None:
        match = re.search(rf"(?:^|\s){re.escape(key)}=([^\t\r\n]+)", line)
        if match:
            value = match.group(1).strip()
            return value if value else None
        return None

    @staticmethod
    def _parse_datetime(value: str) -> datetime | None:
        try:
            dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
            return timezone.make_aware(dt, timezone.get_current_timezone())
        except Exception:
            return None

    @staticmethod
    def _event_hash(device: AccessDevice, event: ParsedEvent) -> str:
        base = "|".join(
            [
                connection.schema_name,
                str(device.id),
                event.event_type,
                event.device_uid,
                event.event_time.isoformat() if event.event_time else "",
                event.raw_line,
            ]
        )
        return hashlib.sha256(base.encode("utf-8")).hexdigest()

    @staticmethod
    def _is_duplicate(device: AccessDevice, event: ParsedEvent) -> bool:
        h = ADMSIngestionService._event_hash(device, event)
        try:
            with transaction.atomic():
                AttendanceIngestEvent.objects.create(
                    access_device=device,
                    event_hash=h,
                    event_type=event.event_type,
                    device_uid=event.device_uid,
                    event_time=event.event_time,
                    raw_line=event.raw_line,
                )
            return False
        except IntegrityError:
            return True

    @staticmethod
    @transaction.atomic
    def _handle_device_user(device: AccessDevice, event: ParsedEvent) -> None:
        defaults = {
            "name": event.name,
            "status": DeviceUser.STATUS_UNLINKED,
        }
        user, created = DeviceUser.objects.get_or_create(
            access_device=device,
            device_uid=event.device_uid,
            defaults=defaults,
        )

        if not created:
            update_fields = ["last_seen_at"]
            if event.name and not user.name:
                user.name = event.name
                update_fields.append("name")
            if user.status == DeviceUser.STATUS_DELETED:
                user.status = DeviceUser.STATUS_UNLINKED
                update_fields.append("status")
            user.save(update_fields=update_fields)

        publish_attendance_event(
            "device-user-seen",
            {
                "access_device_id": device.id,
                "access_device_name": device.name,
                "device_sn": device.device_sn,
                "device_user_id": user.id,
                "device_uid": user.device_uid,
                "name": user.name,
                "status": user.status,
                "created": created,
            },
        )

    @staticmethod
    @transaction.atomic
    def _handle_attlog(device: AccessDevice, event: ParsedEvent) -> None:
        member = Member.objects.filter(fingerprint_id=event.device_uid).first()
        if not member:
            logger.warning("[INGESTION] ATTLOG uid=%s has no linked member — creating unlinked DeviceUser", event.device_uid)
            user, _ = DeviceUser.objects.get_or_create(
                access_device=device,
                device_uid=event.device_uid,
                defaults={"status": DeviceUser.STATUS_UNLINKED},
            )
            publish_attendance_event(
                "unlinked-fingerprint-scanned",
                {
                    "access_device_id": device.id,
                    "access_device_name": device.name,
                    "device_sn": device.device_sn,
                    "device_user_id": user.id,
                    "device_uid": user.device_uid,
                    "name": user.name,
                    "status": user.status,
                },
            )
            return

        open_attendance = Attendance.objects.filter(member=member, check_out_time__isnull=True).first()
        if open_attendance:
            open_attendance.check_out_time = timezone.now()
            open_attendance.save(update_fields=["check_out_time"])
            action = "checked_out"
        else:
            Attendance.objects.create(
                member=member,
                entry_method="fingerprint",
                device_id=device.device_sn,
            )
            action = "checked_in"

        publish_attendance_event(
            "attendance-updated",
            {
                "access_device_id": device.id,
                "device_sn": device.device_sn,
                "member_id": member.id,
                "member_name": member.full_name,
                "action": action,
            },
        )
