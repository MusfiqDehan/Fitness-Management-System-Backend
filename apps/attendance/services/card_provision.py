from __future__ import annotations

from django.db import transaction

from apps.attendance.device_profiles import get_device_profile
from apps.attendance.models import AccessDevice, DeviceUser
from apps.attendance.services.adms_commands import build_userinfo_command, queue_commands
from apps.attendance.services.enrollment import EnrollmentNotSupported, EnrollmentServiceError
from apps.membership.models import Member


class CardProvisionService:
    @classmethod
    @transaction.atomic
    def provision(cls, *, member: Member, device: AccessDevice, user=None) -> dict:
        if not device.is_active:
            raise EnrollmentNotSupported("Access device is inactive.")
        if device.mode not in (AccessDevice.MODE_ADMS, AccessDevice.MODE_TCP_RELAY):
            raise EnrollmentNotSupported("Card provision requires ADMS or TCP Relay mode.")

        profile = get_device_profile(device.device_profile)
        if not profile.supports_card:
            raise EnrollmentNotSupported("Selected device profile does not support cards.")

        card_id = (member.card_id or "").strip()
        if not card_id:
            raise EnrollmentServiceError("Member has no card_id set.")

        # Prefer existing linked device PIN, else fingerprint_id, else allocate next uid
        device_uid = None
        linked = DeviceUser.objects.filter(
            access_device=device,
            member=member,
            status=DeviceUser.STATUS_LINKED,
        ).first()
        if linked:
            device_uid = linked.device_uid
        elif member.fingerprint_id:
            device_uid = member.fingerprint_id
        else:
            from apps.attendance.services.enrollment import FingerprintEnrollmentService

            device_uid = FingerprintEnrollmentService.allocate_device_uid(device)

        cmd = build_userinfo_command(
            profile,
            pin=device_uid,
            name=member.full_name,
            card=card_id,
        )
        queued = queue_commands(device, [cmd])

        device_user, _ = DeviceUser.objects.get_or_create(
            access_device=device,
            device_uid=device_uid,
            defaults={
                "member": member,
                "name": member.full_name,
                "status": DeviceUser.STATUS_LINKED,
                "card_number": card_id,
            },
        )
        update_fields = ["last_seen_at"]
        if device_user.card_number != card_id:
            device_user.card_number = card_id
            update_fields.append("card_number")
        if device_user.member_id != member.id:
            device_user.member = member
            device_user.status = DeviceUser.STATUS_LINKED
            update_fields.extend(["member", "status"])
        device_user.save(update_fields=list(dict.fromkeys(update_fields)))

        return {
            "device_uid": device_uid,
            "card_id": card_id,
            "queued_commands": queued,
            "device_user_id": device_user.id,
        }
