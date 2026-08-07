from __future__ import annotations

from django.db import transaction

from apps.attendance.models import AccessDevice, DeviceUser
from apps.attendance.services.adms_commands import build_delete_userinfo_command, queue_commands
from apps.attendance.services.realtime import publish_attendance_event


class DeviceUserDeleteService:
    """Queue hardware delete first; commit FitPulse delete only after device ACK success."""

    ACTION = "delete_user"

    @classmethod
    @transaction.atomic
    def queue_delete(cls, *, device_user: DeviceUser, device: AccessDevice) -> list[dict]:
        if device_user.status == DeviceUser.STATUS_DELETED:
            raise ValueError("Device user already deleted.")
        if device_user.status == DeviceUser.STATUS_PENDING_DELETE:
            raise ValueError("Device user delete is already pending device confirmation.")
        if not device.is_active:
            raise ValueError("Access device is inactive.")
        if device.mode not in (AccessDevice.MODE_ADMS, AccessDevice.MODE_TCP_RELAY):
            raise ValueError("Delete requires ADMS or TCP Relay mode.")

        previous_status = device_user.status
        device_user.status = DeviceUser.STATUS_PENDING_DELETE
        device_user.save(update_fields=["status", "last_seen_at"])

        queued = queue_commands(
            device,
            [build_delete_userinfo_command(device_user.device_uid)],
            entry_extra={
                "action": cls.ACTION,
                "device_user_id": device_user.id,
                "previous_status": previous_status,
            },
        )

        publish_attendance_event(
            "fingerprint-delete-queued",
            {
                "device_user_id": device_user.id,
                "device_uid": device_user.device_uid,
                "access_device_id": device.id,
                "queued_command_ids": [entry["id"] for entry in queued],
            },
        )
        return queued

    @classmethod
    @transaction.atomic
    def handle_command_ack(
        cls,
        *,
        device: AccessDevice,
        command_id: str,
        return_code: int,
        cmd_echo: str = "",
    ) -> DeviceUser | None:
        meta = dict(device.meta_json or {})
        entry = (meta.get("command_index") or {}).get(str(command_id))
        if not entry or entry.get("action") != cls.ACTION:
            cmd_text = (entry or {}).get("cmd") or meta.get("last_command_sent") or ""
            if "DELETE USERINFO" not in str(cmd_text).upper():
                return None
            # Fallback for older queued commands without action metadata.
            if not entry:
                return None

        device_user_id = entry.get("device_user_id")
        if not device_user_id:
            return None

        device_user = (
            DeviceUser.objects.select_for_update()
            .filter(id=device_user_id, access_device=device)
            .first()
        )
        if not device_user or device_user.status == DeviceUser.STATUS_DELETED:
            return device_user

        if return_code != 0:
            previous = entry.get("previous_status") or DeviceUser.STATUS_UNLINKED
            if previous not in {
                DeviceUser.STATUS_LINKED,
                DeviceUser.STATUS_UNLINKED,
            }:
                previous = DeviceUser.STATUS_UNLINKED
            device_user.status = previous
            device_user.save(update_fields=["status", "last_seen_at"])
            publish_attendance_event(
                "fingerprint-delete-failed",
                {
                    "device_user_id": device_user.id,
                    "device_uid": device_user.device_uid,
                    "access_device_id": device.id,
                    "return_code": return_code,
                    "cmd_echo": cmd_echo,
                    "reason": f"Device rejected delete with code {return_code}.",
                },
            )
            return device_user

        cls._finalize_delete(device_user)
        return device_user

    @classmethod
    def _finalize_delete(cls, device_user: DeviceUser) -> None:
        # Reload member separately — avoid select_for_update + nullable outer join.
        member = device_user.member
        card = (device_user.card_number or "").strip()
        device_uid = device_user.device_uid

        remaining = (
            DeviceUser.objects.filter(
                member=member,
                status__in=[DeviceUser.STATUS_LINKED, DeviceUser.STATUS_PENDING_DELETE],
            ).exclude(pk=device_user.pk)
            if member
            else DeviceUser.objects.none()
        )

        device_user.member = None
        device_user.status = DeviceUser.STATUS_DELETED
        device_user.save(update_fields=["member", "status", "last_seen_at"])

        if member:
            member_updates: list[str] = []
            if card and (member.card_id or "").strip() == card:
                if not remaining.filter(card_number=card).exists():
                    member.card_id = None
                    member_updates.append("card_id")
            if (member.fingerprint_id or "").strip() == device_uid:
                if not remaining.filter(device_uid=device_uid).exists():
                    member.fingerprint_id = None
                    member_updates.append("fingerprint_id")
            if member_updates:
                member.save(update_fields=member_updates)

        publish_attendance_event(
            "fingerprint-deleted",
            {
                "device_user_id": device_user.id,
                "member_id": member.id if member else None,
                "device_uid": device_uid,
                "access_device_id": device_user.access_device_id,
            },
        )
