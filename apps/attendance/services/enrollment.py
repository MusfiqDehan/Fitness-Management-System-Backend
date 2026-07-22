from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.attendance.device_profiles import get_device_profile
from apps.attendance.models import (
	AccessDevice,
	DeviceUser,
	FingerprintEnrollmentSession,
)
from apps.attendance.services.adms_commands import (
	build_remote_enroll_command,
	build_userinfo_command,
	queue_commands,
)
from apps.attendance.services.realtime import publish_attendance_event
from apps.membership.models import Member


class EnrollmentServiceError(Exception):
	"""Base enrollment error."""


class EnrollmentNotSupported(EnrollmentServiceError):
	pass


class EnrollmentConflict(EnrollmentServiceError):
	pass


ACTIVE_ENROLLMENT_STATUSES = {
	FingerprintEnrollmentSession.STATUS_QUEUED,
	FingerprintEnrollmentSession.STATUS_USERINFO_SENT,
	FingerprintEnrollmentSession.STATUS_ENROLL_SENT,
	FingerprintEnrollmentSession.STATUS_AWAITING_SCAN,
}

ENROLLMENT_TTL = timedelta(minutes=15)


class FingerprintEnrollmentService:
	@staticmethod
	def _active_sessions_for_device(device: AccessDevice):
		return FingerprintEnrollmentSession.objects.filter(
			access_device=device,
			status__in=ACTIVE_ENROLLMENT_STATUSES,
		)

	@staticmethod
	def allocate_device_uid(device: AccessDevice) -> str:
		profile = get_device_profile(device.device_profile)
		used: set[int] = set()

		for uid in DeviceUser.objects.filter(access_device=device).values_list("device_uid", flat=True):
			if str(uid).isdigit():
				used.add(int(uid))

		for uid in FingerprintEnrollmentService._active_sessions_for_device(device).values_list(
			"device_uid", flat=True
		):
			if str(uid).isdigit():
				used.add(int(uid))

		for candidate in range(1, profile.max_users + 1):
			if candidate not in used:
				return str(candidate)

		raise EnrollmentConflict("No available device PIN on this access device.")

	@staticmethod
	def _publish(event: str, payload: dict) -> None:
		publish_attendance_event(event, payload)

	@staticmethod
	def _trace_append(session: FingerprintEnrollmentSession, entry: dict) -> None:
		trace = list(session.command_trace or [])
		trace.append(entry)
		session.command_trace = trace

	@classmethod
	@transaction.atomic
	def start_enrollment(
		cls,
		*,
		member: Member,
		device: AccessDevice,
		user,
		fingerprint_slot: int = 0,
	) -> FingerprintEnrollmentSession:
		if device.mode not in (AccessDevice.MODE_ADMS, AccessDevice.MODE_TCP_RELAY):
			raise EnrollmentNotSupported("Remote enrollment requires ADMS or TCP Relay mode.")
		if not device.is_active:
			raise EnrollmentNotSupported("Access device is inactive.")

		profile = get_device_profile(device.device_profile)
		if not profile.supports_remote_enroll:
			raise EnrollmentNotSupported("Selected device profile does not support remote enrollment.")

		if cls._active_sessions_for_device(device).exists():
			raise EnrollmentConflict("Device already has an active enrollment session.")

		if member.fingerprint_id:
			raise EnrollmentConflict("Member already has a linked fingerprint.")

		device_uid = cls.allocate_device_uid(device)
		session = FingerprintEnrollmentSession.objects.create(
			access_device=device,
			member=member,
			device_uid=device_uid,
			fingerprint_slot=fingerprint_slot,
			status=FingerprintEnrollmentSession.STATUS_QUEUED,
			expires_at=timezone.now() + ENROLLMENT_TTL,
			created_by=user if getattr(user, "is_authenticated", False) else None,
		)

		userinfo_cmd = build_userinfo_command(
			profile,
			pin=device_uid,
			name=member.full_name,
			card=member.card_id or "",
		)
		enroll_cmd = build_remote_enroll_command(
			profile,
			pin=device_uid,
			fingerprint_slot=fingerprint_slot,
		)
		queued = queue_commands(device, [userinfo_cmd, enroll_cmd], session_id=session.id)

		for entry in queued:
			cls._trace_append(
				session,
				{
					"id": entry["id"],
					"cmd": entry["cmd"],
					"queued_at": timezone.now().isoformat(),
				},
			)
		session.save(update_fields=["command_trace", "updated_at"])

		cls._publish(
			"enrollment-started",
			{
				"session_id": session.id,
				"member_id": member.id,
				"member_name": member.full_name,
				"access_device_id": device.id,
				"access_device_name": device.name,
				"device_uid": device_uid,
				"status": session.status,
			},
		)
		return session

	@classmethod
	@transaction.atomic
	def cancel_enrollment(cls, session: FingerprintEnrollmentSession) -> FingerprintEnrollmentSession:
		if session.status in {
			FingerprintEnrollmentSession.STATUS_COMPLETED,
			FingerprintEnrollmentSession.STATUS_CANCELLED,
			FingerprintEnrollmentSession.STATUS_EXPIRED,
		}:
			return session

		session.status = FingerprintEnrollmentSession.STATUS_CANCELLED
		session.save(update_fields=["status", "updated_at"])
		cls._publish(
			"enrollment-cancelled",
			{"session_id": session.id, "member_id": session.member_id},
		)
		return session

	@classmethod
	def expire_if_needed(cls, session: FingerprintEnrollmentSession) -> FingerprintEnrollmentSession:
		if session.status in ACTIVE_ENROLLMENT_STATUSES and session.expires_at <= timezone.now():
			session.status = FingerprintEnrollmentSession.STATUS_EXPIRED
			session.failure_reason = "Enrollment session expired."
			session.save(update_fields=["status", "failure_reason", "updated_at"])
			cls._publish(
				"enrollment-failed",
				{
					"session_id": session.id,
					"member_id": session.member_id,
					"reason": session.failure_reason,
				},
			)
		return session

	@classmethod
	@transaction.atomic
	def handle_command_ack(
		cls,
		*,
		device: AccessDevice,
		command_id: str,
		return_code: int,
		cmd_echo: str = "",
	) -> FingerprintEnrollmentSession | None:
		session_id = None
		meta = dict(device.meta_json or {})
		command_index = meta.get("command_index", {})
		entry = command_index.get(str(command_id))
		if entry:
			session_id = entry.get("session_id")
		if session_id is None:
			session_id = meta.get("last_command_session_id")

		if not session_id:
			return None

		session = (
			FingerprintEnrollmentSession.objects.select_for_update()
			.filter(id=session_id, access_device=device)
			.first()
		)
		if not session:
			return None

		cls.expire_if_needed(session)
		if session.status not in ACTIVE_ENROLLMENT_STATUSES:
			return session

		cls._trace_append(
			session,
			{
				"id": command_id,
				"ack_return": return_code,
				"ack_cmd": cmd_echo,
				"ack_at": timezone.now().isoformat(),
			},
		)

		if return_code != 0:
			session.status = FingerprintEnrollmentSession.STATUS_FAILED
			session.failure_reason = f"Device command failed with code {return_code}."
			session.save(update_fields=["status", "failure_reason", "command_trace", "updated_at"])
			cls._publish(
				"enrollment-failed",
				{
					"session_id": session.id,
					"member_id": session.member_id,
					"reason": session.failure_reason,
					"return_code": return_code,
				},
			)
			return session

		cmd_text = (entry or {}).get("cmd", meta.get("last_command_sent", ""))
		if cmd_text.startswith("DATA UPDATE USERINFO"):
			session.status = FingerprintEnrollmentSession.STATUS_USERINFO_SENT
			cls._publish(
				"enrollment-progress",
				{
					"session_id": session.id,
					"step": "userinfo_sent",
					"message": "User created on device.",
				},
			)
		elif cmd_text.startswith("ENROLL_FP"):
			if device.mode == AccessDevice.MODE_TCP_RELAY:
				# LAN agent confirms template on device; complete without waiting for FP push.
				session.save(update_fields=["command_trace", "updated_at"])
				linked = cls.handle_fingerprint_ingested(
					device=device,
					device_uid=session.device_uid,
				)
				return linked or session
			session.status = FingerprintEnrollmentSession.STATUS_AWAITING_SCAN
			cls._publish(
				"enrollment-awaiting-scan",
				{
					"session_id": session.id,
					"member_id": session.member_id,
					"access_device_name": device.name,
					"device_uid": session.device_uid,
				},
			)
		else:
			session.status = FingerprintEnrollmentSession.STATUS_ENROLL_SENT

		session.save(update_fields=["status", "command_trace", "updated_at"])
		return session

	@classmethod
	@transaction.atomic
	def handle_fingerprint_ingested(
		cls,
		*,
		device: AccessDevice,
		device_uid: str,
	) -> FingerprintEnrollmentSession | None:
		session = (
			FingerprintEnrollmentSession.objects.select_for_update()
			.filter(
				access_device=device,
				device_uid=device_uid,
				status__in={
					FingerprintEnrollmentSession.STATUS_AWAITING_SCAN,
					FingerprintEnrollmentSession.STATUS_ENROLL_SENT,
					FingerprintEnrollmentSession.STATUS_USERINFO_SENT,
					FingerprintEnrollmentSession.STATUS_QUEUED,
				},
			)
			.order_by("-created_at")
			.first()
		)
		if not session:
			return None

		cls.expire_if_needed(session)
		if session.status not in ACTIVE_ENROLLMENT_STATUSES:
			return session

		member = session.member
		conflict = Member.objects.filter(fingerprint_id=device_uid).exclude(id=member.id).first()
		if conflict:
			session.status = FingerprintEnrollmentSession.STATUS_FAILED
			session.failure_reason = (
				f"Device PIN {device_uid} is already linked to {conflict.full_name}."
			)
			session.save(update_fields=["status", "failure_reason", "updated_at"])
			cls._publish(
				"enrollment-failed",
				{
					"session_id": session.id,
					"member_id": session.member_id,
					"reason": session.failure_reason,
				},
			)
			return session

		device_user, _ = DeviceUser.objects.get_or_create(
			access_device=device,
			device_uid=device_uid,
			defaults={
				"name": member.full_name,
				"status": DeviceUser.STATUS_LINKED,
				"member": member,
			},
		)
		if device_user.member_id != member.id or device_user.status != DeviceUser.STATUS_LINKED:
			device_user.member = member
			device_user.name = member.full_name
			device_user.status = DeviceUser.STATUS_LINKED
			device_user.save(update_fields=["member", "name", "status", "last_seen_at"])

		member.fingerprint_id = device_uid
		member.save(update_fields=["fingerprint_id"])

		session.status = FingerprintEnrollmentSession.STATUS_COMPLETED
		session.save(update_fields=["status", "updated_at"])

		cls._publish(
			"enrollment-completed",
			{
				"session_id": session.id,
				"member_id": member.id,
				"member_name": member.full_name,
				"device_uid": device_uid,
				"device_user_id": device_user.id,
			},
		)
		cls._publish(
			"fingerprint-linked",
			{
				"device_user_id": device_user.id,
				"member_id": member.id,
				"member_name": member.full_name,
			},
		)
		return session
