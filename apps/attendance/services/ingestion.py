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
from apps.attendance.services.session import apply_member_punch

logger = logging.getLogger(__name__)

# ZKTeco verify-type → Attendance.entry_method. Unknown codes default to fingerprint.
VERIFY_TO_ENTRY_METHOD = {
    1: "fingerprint",
    2: "card",
    3: "card",  # password + card
}


@dataclass
class ParsedEvent:
    event_type: str
    device_uid: str
    event_time: datetime | None
    raw_line: str
    name: str | None = None
    verify_mode: int | None = None
    status: int | None = None
    in_out: int | None = None
    card_number: str | None = None


class ADMSIngestionService:
    @staticmethod
    def process(device: AccessDevice, raw_body: str, table_hint: str | None = None) -> dict:
        events = ADMSIngestionService._parse_body(raw_body or "", table_hint=table_hint)
        logger.debug("[INGESTION] SN=%s parsed %d events from body", device.device_sn, len(events))
        handled = 0
        skipped = 0

        for event in events:
            logger.debug(
                "[INGESTION] SN=%s event type=%s uid=%s time=%s verify=%s",
                device.device_sn,
                event.event_type,
                event.device_uid,
                event.event_time,
                event.verify_mode,
            )
            if ADMSIngestionService._is_duplicate(device, event):
                logger.debug(
                    "[INGESTION] SN=%s DUPLICATE type=%s uid=%s",
                    device.device_sn,
                    event.event_type,
                    event.device_uid,
                )
                skipped += 1
                continue

            if event.event_type == "ATTLOG":
                ADMSIngestionService._handle_attlog(device, event)
            elif event.event_type in {"USERINFO", "FP", "OPERLOG"}:
                ADMSIngestionService._handle_device_user(device, event)
                if event.event_type == "FP":
                    try:
                        FingerprintEnrollmentService.handle_fingerprint_ingested(
                            device=device,
                            device_uid=event.device_uid,
                        )
                    except Exception:
                        logger.exception(
                            "[INGESTION] FP ingest failed SN=%s uid=%s",
                            device.device_sn,
                            event.device_uid,
                        )

            handled += 1
            logger.info(
                "[INGESTION] SN=%s handled type=%s uid=%s name=%s",
                device.device_sn,
                event.event_type,
                event.device_uid,
                event.name,
            )

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
                parts = [p.strip() for p in line.split("\t")]
                # Keep empty trailing cells but require at least PIN + time
                nonempty = [p for p in parts if p]
                if len(nonempty) < 2:
                    continue
                uid = parts[0]
                dt = ADMSIngestionService._parse_datetime(parts[1])
                status = ADMSIngestionService._parse_int(parts[2]) if len(parts) > 2 and parts[2] != "" else None
                verify = ADMSIngestionService._parse_int(parts[3]) if len(parts) > 3 and parts[3] != "" else None
                in_out = ADMSIngestionService._parse_int(parts[4]) if len(parts) > 4 and parts[4] != "" else None
                out.append(
                    ParsedEvent(
                        "ATTLOG",
                        uid,
                        dt,
                        line,
                        verify_mode=verify,
                        status=status,
                        in_out=in_out,
                    )
                )
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
                card = ADMSIngestionService._extract_kv_field(line, "Card")
                out.append(
                    ParsedEvent(
                        current_table,
                        uid,
                        None,
                        line,
                        name=name,
                        card_number=card,
                    )
                )

        return out

    @staticmethod
    def _parse_int(value: str) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

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
    def entry_method_for_verify(verify_mode: int | None) -> str:
        """Map ZKTeco verify codes to Attendance.entry_method (card|fingerprint)."""
        if verify_mode is None:
            return "fingerprint"
        return VERIFY_TO_ENTRY_METHOD.get(int(verify_mode), "fingerprint")

    @staticmethod
    def verify_method_label(verify_mode: int | None) -> str:
        labels = {
            0: "password",
            1: "fingerprint",
            2: "card",
            3: "pin",
            4: "face",
        }
        if verify_mode is None:
            return "fingerprint"
        return labels.get(int(verify_mode), "fingerprint")

    @staticmethod
    def _resolve_member(device: AccessDevice, event: ParsedEvent) -> Member | None:
        linked = (
            DeviceUser.objects.filter(
                access_device=device,
                device_uid=event.device_uid,
                status=DeviceUser.STATUS_LINKED,
                member__isnull=False,
            )
            .select_related("member")
            .first()
        )
        if linked and linked.member_id:
            return linked.member

        member = Member.objects.filter(fingerprint_id=event.device_uid).first()
        if member:
            return member

        if event.verify_mode == 2:
            # Card scan: try DeviceUser.card_number → member.card_id
            device_user = DeviceUser.objects.filter(
                access_device=device,
                device_uid=event.device_uid,
            ).first()
            card = (device_user.card_number if device_user else None) or None
            if card:
                member = Member.objects.filter(card_id=card).first()
                if member:
                    return member
            # Fallback: any member whose card_id equals device PIN (rare)
            member = Member.objects.filter(card_id=event.device_uid).first()
            if member:
                return member

        return None

    @staticmethod
    @transaction.atomic
    def _handle_device_user(device: AccessDevice, event: ParsedEvent) -> None:
        defaults = {
            "name": event.name,
            "status": DeviceUser.STATUS_UNLINKED,
            "card_number": event.card_number or "",
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
            if event.card_number and user.card_number != event.card_number:
                user.card_number = event.card_number
                update_fields.append("card_number")
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
                "card_number": user.card_number,
                "status": user.status,
                "created": created,
            },
        )

    @staticmethod
    @transaction.atomic
    def _handle_attlog(device: AccessDevice, event: ParsedEvent) -> None:
        entry_method = ADMSIngestionService.entry_method_for_verify(event.verify_mode)
        verify_label = ADMSIngestionService.verify_method_label(event.verify_mode)
        member = ADMSIngestionService._resolve_member(device, event)
        if not member:
            logger.warning(
                "[INGESTION] ATTLOG uid=%s verify=%s has no linked member — creating unlinked DeviceUser",
                event.device_uid,
                event.verify_mode,
            )
            user, _ = DeviceUser.objects.get_or_create(
                access_device=device,
                device_uid=event.device_uid,
                defaults={"status": DeviceUser.STATUS_UNLINKED},
            )
            payload = {
                "access_device_id": device.id,
                "access_device_name": device.name,
                "device_sn": device.device_sn,
                "device_user_id": user.id,
                "device_uid": user.device_uid,
                "name": user.name,
                "status": user.status,
                "verify_method": verify_label,
                "verify_mode": event.verify_mode,
            }
            publish_attendance_event("unlinked-device-scan", payload)
            publish_attendance_event("unlinked-fingerprint-scanned", payload)
            return

        action = apply_member_punch(
            member,
            entry_method=entry_method,
            device_id=device.device_sn,
            device_uid=event.device_uid,
            at=event.event_time or timezone.now(),
        )
        if not action:
            return

        publish_attendance_event(
            "attendance-updated",
            {
                "access_device_id": device.id,
                "device_sn": device.device_sn,
                "member_id": member.id,
                "member_name": member.full_name,
                "action": action,
                "entry_method": entry_method,
            },
        )
