from datetime import date, timedelta
import hashlib
import hmac
import logging
import secrets
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import connection
from django.db import transaction
from django.db.models import Max
from django.http import HttpResponse as PlainTextResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django_tenants.utils import get_public_schema_name, schema_context
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status
from rest_framework.generics import ListAPIView, ListCreateAPIView, RetrieveUpdateDestroyAPIView
from rest_framework.permissions import AllowAny
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access.permissions import HasFeatureMethodPermission
from apps.membership.models import Attendance, Member
from apps.tenancy.models import AccessDeviceRoute, Tenant
from utils.pagination import StandardPagination
from utils.cache_helpers import STATS_TTL, get_cached_value, stats_key, stats_scope_token
from utils.tenancy_helpers import scope_queryset_by_branch_access
from .models import AccessDevice, AttendanceIngestEvent, DeviceCredential, DeviceUser, FingerprintEnrollmentSession

logger = logging.getLogger(__name__)
from .device_profiles import list_device_profiles
from .services.adms_commands import (
	build_attlog_sync_command,
	build_delete_userinfo_command,
	build_push_handshake_body,
	dequeue_next_command,
	parse_devicecmd_body,
	queue_commands,
	lookup_queued_command,
)
from .services.card_provision import CardProvisionService
from .services.enrollment import (
	EnrollmentConflict,
	EnrollmentNotSupported,
	EnrollmentServiceError,
	FingerprintEnrollmentService,
)
from .services.ingestion import ADMSIngestionService
from .services.realtime import publish_attendance_event
from .services.session import apply_member_punch
from .services.stats import AttendanceStatsService
from .serializers import (
	AccessDeviceSerializer,
	AttendanceLogSerializer,
	CardProvisionSerializer,
	DeviceCredentialRotateSerializer,
	DeviceUserSerializer,
	FingerprintDeleteSerializer,
	FingerprintLinkSerializer,
	FingerprintUnlinkSerializer,
	FingerprintEnrollmentStartSerializer,
	FingerprintEnrollmentSessionSerializer,
	member_credential_linked,
)


class DeviceAPIKeyPermission(BasePermission):
	"""Allow machine-to-machine access for gym devices using X-API-KEY."""

	def has_permission(self, request, view):
		expected = getattr(settings, "GYM_DEVICE_API_KEY", "")
		incoming = request.headers.get("X-API-KEY", "")
		if not expected or not incoming:
			return False
		return hmac.compare_digest(incoming, expected)


class DeviceOrFeatureMethodPermission(BasePermission):
	"""Allow valid device API key OR tenant user with feature permission."""

	def has_permission(self, request, view):
		if DeviceAPIKeyPermission().has_permission(request, view):
			return True
		return HasFeatureMethodPermission().has_permission(request, view)


class AccessCheckAPIView(APIView):
	"""Canonical access gate endpoint owned by attendance app."""

	feature_key = "attendance.access_gate"
	method_permission_map = {
		"POST": "edit",
	}
	permission_classes = [DeviceOrFeatureMethodPermission]

	def post(self, request):
		card_id = request.data.get("card_id")
		fingerprint_id = request.data.get("fingerprint_id")
		device_id = request.data.get("device_id")
		access_device_id = request.data.get("access_device_id")
		device_sn = request.data.get("device_sn")

		access_device = None
		if access_device_id:
			access_device = AccessDevice.objects.filter(id=access_device_id, is_active=True).first()
		elif device_sn:
			access_device = AccessDevice.objects.filter(device_sn=device_sn, is_active=True).first()

		if access_device_id or device_sn:
			if not access_device:
				return Response(
					{"access": False, "message": "Unrecognized or inactive access device"},
					status=status.HTTP_403_FORBIDDEN,
				)

		member = None
		if card_id:
			member = Member.objects.filter(card_id=card_id).first()
		if fingerprint_id:
			member = Member.objects.filter(fingerprint_id=fingerprint_id).first()

		if not member:
			return Response(
				{"access": False, "message": "Member not found"},
				status=status.HTTP_404_NOT_FOUND,
			)

		if not member.is_valid:
			return Response(
				{"access": False, "message": "Membership expired or inactive"},
				status=status.HTTP_403_FORBIDDEN,
			)

		entry_method = "card" if card_id else "fingerprint"
		device_ref = device_id or (access_device.device_sn if access_device else None)
		action = apply_member_punch(
			member,
			entry_method=entry_method,
			device_id=device_ref,
		)
		if not action:
			return Response(
				{
					"access": True,
					"action": "ignored",
					"message": "Duplicate scan ignored",
					"member_name": member.full_name,
				}
			)

		if action == "checked_out":
			publish_attendance_event(
				"attendance-updated",
				{
					"member_id": member.id,
					"member_name": member.full_name,
					"action": "checked_out",
					"device_sn": device_ref,
				},
			)
			return Response(
				{
					"access": True,
					"action": "checked_out",
					"member_name": member.full_name,
				}
			)

		try:
			from apps.membership.services.class_attendance import ClassAttendanceService
			ClassAttendanceService.try_match_member_check_in(member, timezone.now())
		except Exception:
			pass
		publish_attendance_event(
			"attendance-updated",
			{
				"member_id": member.id,
				"member_name": member.full_name,
				"action": "checked_in",
				"device_sn": device_ref,
			},
		)
		return Response(
			{
				"access": True,
				"action": "checked_in",
				"member_name": member.full_name,
				"remaining_days": member.remaining_days,
			}
		)


class MembersInsideAPIView(APIView):
	"""Canonical "currently inside" endpoint owned by attendance app."""

	feature_keys = ["attendance.access_gate", "members.attendance"]
	permission_classes = [DeviceOrFeatureMethodPermission]

	def get(self, request):
		inside_members = Attendance.objects.filter(
			check_out_time__isnull=True,
		).select_related("member")
		inside_members = scope_queryset_by_branch_access(
			inside_members,
			request.user,
			branch_field="member__branch_id",
			branch_filter_id=request.query_params.get("branch"),
		)

		data = [
			{
				"member_name": record.member.full_name,
				"phone": record.member.phone_number,
				"check_in_time": record.check_in_time,
			}
			for record in inside_members
		]

		return Response({
			"total_inside": inside_members.count(),
			"members": data,
		})


class DeviceRegistryListCreateAPIView(ListCreateAPIView):
	"""Attendance-owned device registry list/create endpoint."""

	feature_key = "attendance.devices"
	permission_classes = [HasFeatureMethodPermission]
	queryset = AccessDevice.objects.all().order_by("-updated_at")
	serializer_class = AccessDeviceSerializer


class DeviceRegistryDetailAPIView(RetrieveUpdateDestroyAPIView):
	"""Attendance-owned device registry detail endpoint."""

	feature_key = "attendance.devices"
	permission_classes = [HasFeatureMethodPermission]
	queryset = AccessDevice.objects.all().order_by("-updated_at")
	serializer_class = AccessDeviceSerializer


class _DeviceActionBaseAPIView(APIView):
	feature_key = "attendance.devices"
	method_permission_map = {"POST": "edit"}
	permission_classes = [HasFeatureMethodPermission]

	def get_object(self, pk):
		return get_object_or_404(AccessDevice, pk=pk)


class DeviceActivateAPIView(_DeviceActionBaseAPIView):
	def post(self, request, pk):
		device = self.get_object(pk)
		device.is_active = True
		if device.status == AccessDevice.STATUS_UNKNOWN:
			device.status = AccessDevice.STATUS_OFFLINE
		device.save(update_fields=["is_active", "status", "updated_at"])
		return Response({"detail": "Device activated.", "id": device.id, "is_active": device.is_active})


class DeviceDeactivateAPIView(_DeviceActionBaseAPIView):
	def post(self, request, pk):
		device = self.get_object(pk)
		device.is_active = False
		device.status = AccessDevice.STATUS_OFFLINE
		device.save(update_fields=["is_active", "status", "updated_at"])
		return Response({"detail": "Device deactivated.", "id": device.id, "is_active": device.is_active})


def _build_attlog_sync_command(device: AccessDevice) -> tuple[str, str]:
	return build_attlog_sync_command(device)


class DeviceSyncNowAPIView(_DeviceActionBaseAPIView):
	def post(self, request, pk):
		device = self.get_object(pk)
		meta = dict(device.meta_json or {})
		meta["last_sync_requested_at"] = timezone.now().isoformat()
		attlog_command, attlog_start_time = _build_attlog_sync_command(device)
		queue_commands(
			device,
			["DATA QUERY USERINFO", attlog_command],
		)
		device.refresh_from_db()
		meta = dict(device.meta_json or {})
		meta["last_sync_requested_at"] = timezone.now().isoformat()
		device.meta_json = meta
		device.save(update_fields=["meta_json", "updated_at"])
		pending_count = len((device.meta_json or {}).get("pending_commands", []))
		return Response({
			"detail": "Device sync queued. Commands will be sent on next device poll.",
			"id": device.id,
			"last_sync_requested_at": meta["last_sync_requested_at"],
			"attlog_start_time": attlog_start_time,
			"commands_queued": pending_count,
		})


class DeviceTestConnectionAPIView(_DeviceActionBaseAPIView):
	def post(self, request, pk):
		device = self.get_object(pk)
		healthy = bool(device.is_active and device.status in (AccessDevice.STATUS_ONLINE, AccessDevice.STATUS_OFFLINE))
		return Response(
			{
				"id": device.id,
				"healthy": healthy,
				"status": device.status,
				"mode": device.mode,
				"message": "Connection profile looks valid." if healthy else "Device is inactive or in error state.",
			},
			status=status.HTTP_200_OK if healthy else status.HTTP_409_CONFLICT,
		)


class DeviceRotateSecretAPIView(_DeviceActionBaseAPIView):
	def post(self, request, pk):
		device = self.get_object(pk)
		plain_secret = secrets.token_urlsafe(32)
		secret_hash = hashlib.sha256(plain_secret.encode("utf-8")).hexdigest()

		meta = dict(device.meta_json or {})
		meta["secret_hash"] = secret_hash
		meta["secret_rotated_at"] = timezone.now().isoformat()
		device.meta_json = meta
		device.save(update_fields=["meta_json", "updated_at"])

		# Never expose full secret in API response.
		preview = f"{plain_secret[:4]}...{plain_secret[-4:]}"
		return Response({
			"detail": "Device secret rotated.",
			"id": device.id,
			"secret_preview": preview,
			"secret_rotated_at": meta["secret_rotated_at"],
		})


class DeviceHealthAPIView(APIView):
	feature_key = "attendance.devices"
	permission_classes = [HasFeatureMethodPermission]

	def get(self, request, pk):
		device = get_object_or_404(AccessDevice, pk=pk)
		meta = dict(device.meta_json or {})
		return Response(
			{
				"id": device.id,
				"status": device.status,
				"is_active": device.is_active,
				"last_seen_at": device.last_seen_at,
				"last_sync_requested_at": meta.get("last_sync_requested_at"),
				"last_error": meta.get("last_error"),
				"queue_lag_sec": meta.get("queue_lag_sec", 0),
			}
		)


def _parse_int_query_param(value):
	if value in (None, ""):
		return None
	try:
		return int(value)
	except (TypeError, ValueError):
		return None


def _apply_attendance_date_filters(queryset, query_params, *, default_mode="day"):
	raw_day = (query_params.get("day") or "").strip()
	if raw_day:
		try:
			day_value = date.fromisoformat(raw_day)
		except ValueError:
			return queryset.none()
		return queryset.filter(check_in_time__date=day_value)

	month_value = _parse_int_query_param(query_params.get("month"))
	year_value = _parse_int_query_param(query_params.get("year"))

	if month_value is not None:
		if month_value < 1 or month_value > 12:
			return queryset.none()
		effective_year = year_value if year_value and year_value > 0 else timezone.localdate().year
		return queryset.filter(check_in_time__year=effective_year, check_in_time__month=month_value)

	if year_value is not None:
		if year_value <= 0:
			return queryset.none()
		return queryset.filter(check_in_time__year=year_value)

	today = timezone.localdate()
	if default_mode == "month":
		return queryset.filter(check_in_time__year=today.year, check_in_time__month=today.month)
	return queryset.filter(check_in_time__date=today)


class AttendanceLogListAPIView(ListAPIView):
	feature_keys = ["members.attendance", "attendance.access_gate"]
	permission_classes = [HasFeatureMethodPermission]
	serializer_class = AttendanceLogSerializer
	pagination_class = StandardPagination
	filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
	filterset_fields = ["entry_method"]
	search_fields = ["member__full_name", "device_id"]
	ordering_fields = ["id", "check_in_time", "check_out_time", "member__full_name", "device_id"]
	ordering = ["-check_in_time"]

	def get_queryset(self):
		queryset = Attendance.objects.select_related("member").order_by("-check_in_time")
		queryset = scope_queryset_by_branch_access(
			queryset,
			self.request.user,
			branch_field="member__branch_id",
			branch_filter_id=self.request.query_params.get("branch"),
		)
		queryset = _apply_attendance_date_filters(
			queryset,
			self.request.query_params,
			default_mode="day",
		)
		device_sn = self.request.query_params.get("device_sn")
		if device_sn:
			queryset = queryset.filter(device_id=device_sn)

		checkout_status = (self.request.query_params.get("checkout_status") or "").strip().lower()
		if checkout_status == "inside":
			queryset = queryset.filter(check_out_time__isnull=True)
		elif checkout_status == "completed":
			queryset = queryset.filter(check_out_time__isnull=False)

		return queryset


class AttendanceStatsAPIView(APIView):
	feature_keys = ["members.attendance", "attendance.access_gate"]
	permission_classes = [HasFeatureMethodPermission]

	def get(self, request):
		branch_filter = request.query_params.get("branch")
		device_sn = (request.query_params.get("device_sn") or "").strip() or None
		hourly_range = (request.query_params.get("hourly_range") or "today").strip().lower()
		heatmap_range = (request.query_params.get("heatmap_range") or "this_year").strip().lower()
		streak_range = (request.query_params.get("streak_range") or "this_year").strip().lower()

		schema_name = connection.schema_name
		scope = stats_scope_token(request.user, branch_filter)
		cache_scope = (
			f"{scope}:d={device_sn or ''}:h={hourly_range}:m={heatmap_range}:s={streak_range}"
		)

		def load():
			return AttendanceStatsService.build_payload(
				request.user,
				branch_filter_id=branch_filter,
				device_sn=device_sn,
				hourly_range=hourly_range,
				heatmap_range=heatmap_range,
				streak_range=streak_range,
			)

		payload = get_cached_value(
			stats_key(schema_name, "attendance_stats", cache_scope),
			STATS_TTL,
			load,
		)
		return Response(payload)


class MemberAttendanceLogListAPIView(ListAPIView):
	permission_classes = [IsAuthenticated]
	serializer_class = AttendanceLogSerializer
	pagination_class = StandardPagination
	filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
	filterset_fields = ["entry_method"]
	search_fields = ["device_id"]
	ordering_fields = ["id", "check_in_time", "check_out_time", "device_id"]
	ordering = ["-check_in_time"]

	def get_queryset(self):
		queryset = Attendance.objects.select_related("member").order_by("-check_in_time")
		try:
			member = self.request.user.member
		except ObjectDoesNotExist:
			return queryset.none()

		queryset = queryset.filter(member=member)

		checkout_status = (self.request.query_params.get("checkout_status") or "").strip().lower()
		if checkout_status == "inside":
			queryset = queryset.filter(check_out_time__isnull=True)
		elif checkout_status == "completed":
			queryset = queryset.filter(check_out_time__isnull=False)

		return _apply_attendance_date_filters(
			queryset,
			self.request.query_params,
			default_mode="month",
		)


class MemberCredentialsAPIView(APIView):
	"""Return the authenticated member's linked credentials and last-use timestamps."""

	permission_classes = [IsAuthenticated]

	_EMPTY = {
		"credential_linked": "none",
		"last_used_at": None,
		"last_entry_method": None,
		"last_fingerprint_used_at": None,
		"last_card_used_at": None,
	}

	def get(self, request):
		try:
			member = request.user.member
		except ObjectDoesNotExist:
			return Response(self._EMPTY)

		logs = Attendance.objects.filter(member=member)
		last_fingerprint = logs.filter(entry_method="fingerprint").aggregate(
			value=Max("check_in_time")
		)["value"]
		last_card = logs.filter(entry_method="card").aggregate(value=Max("check_in_time"))["value"]
		latest = (
			logs.order_by("-check_in_time")
			.values("check_in_time", "entry_method")
			.first()
		)

		return Response(
			{
				"credential_linked": member_credential_linked(member),
				"last_used_at": latest["check_in_time"] if latest else None,
				"last_entry_method": latest["entry_method"] if latest else None,
				"last_fingerprint_used_at": last_fingerprint,
				"last_card_used_at": last_card,
			}
		)


class FingerprintUnlinkedListAPIView(ListAPIView):
	feature_key = "attendance.fingerprints"
	permission_classes = [HasFeatureMethodPermission]
	serializer_class = DeviceUserSerializer
	pagination_class = StandardPagination
	filter_backends = [SearchFilter]
	search_fields = ["device_uid", "name", "access_device__name", "card_number"]

	def get_queryset(self):
		queryset = DeviceUser.objects.exclude(status=DeviceUser.STATUS_DELETED).select_related(
			"member", "access_device"
		)
		status_filter = (self.request.query_params.get("status") or "").strip().lower()
		if status_filter in {DeviceUser.STATUS_UNLINKED, DeviceUser.STATUS_LINKED}:
			queryset = queryset.filter(status=status_filter)
		access_device_id = self.request.query_params.get("access_device_id")
		if access_device_id:
			queryset = queryset.filter(access_device_id=access_device_id)
		return queryset.order_by("-last_seen_at")


class FingerprintLinkAPIView(APIView):
	feature_key = "attendance.fingerprints"
	method_permission_map = {"POST": "edit"}
	permission_classes = [HasFeatureMethodPermission]

	def post(self, request):
		serializer = FingerprintLinkSerializer(data=request.data)
		serializer.is_valid(raise_exception=True)
		device_user = serializer.validated_data["device_user"]
		member = serializer.validated_data["member"]

		with transaction.atomic():
			device_user.member = member
			device_user.status = DeviceUser.STATUS_LINKED
			device_user.save(update_fields=["member", "status", "last_seen_at"])

			member_updates: list[str] = []
			card = (device_user.card_number or "").strip()
			if card and not (member.card_id or "").strip():
				member.card_id = card
				member_updates.append("card_id")

			# Fingerprint-only identities fill empty fingerprint_id (never overwrite).
			# Card-only slots must not set fingerprint_id.
			if not card and not (member.fingerprint_id or "").strip():
				member.fingerprint_id = device_user.device_uid
				member_updates.append("fingerprint_id")

			if member_updates:
				member.save(update_fields=member_updates)

		publish_attendance_event(
			"fingerprint-linked",
			{
				"device_user_id": device_user.id,
				"member_id": member.id,
				"member_name": member.full_name,
			},
		)

		return Response({"detail": "Fingerprint linked.", "device_user_id": device_user.id, "member_id": member.id})


class FingerprintUnlinkAPIView(APIView):
	feature_key = "attendance.fingerprints"
	method_permission_map = {"POST": "edit"}
	permission_classes = [HasFeatureMethodPermission]

	def post(self, request):
		serializer = FingerprintUnlinkSerializer(data=request.data)
		serializer.is_valid(raise_exception=True)
		device_user = get_object_or_404(DeviceUser, id=serializer.validated_data["device_user_id"])
		member = device_user.member
		card = (device_user.card_number or "").strip()
		device_uid = device_user.device_uid

		with transaction.atomic():
			remaining = (
				DeviceUser.objects.filter(member=member, status=DeviceUser.STATUS_LINKED).exclude(
					pk=device_user.pk
				)
				if member
				else DeviceUser.objects.none()
			)

			device_user.member = None
			device_user.status = DeviceUser.STATUS_UNLINKED
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
			"fingerprint-unlinked",
			{
				"device_user_id": device_user.id,
				"member_id": member.id if member else None,
			},
		)

		return Response({"detail": "Fingerprint unlinked.", "device_user_id": device_user.id})


class FingerprintDeleteAPIView(APIView):
	feature_key = "attendance.fingerprints"
	method_permission_map = {"POST": "edit"}
	permission_classes = [HasFeatureMethodPermission]

	def post(self, request):
		serializer = FingerprintDeleteSerializer(data=request.data)
		serializer.is_valid(raise_exception=True)
		device_user = serializer.validated_data["device_user"]
		device = serializer.validated_data["device"]
		member = device_user.member
		card = (device_user.card_number or "").strip()
		device_uid = device_user.device_uid

		with transaction.atomic():
			remaining = (
				DeviceUser.objects.filter(member=member, status=DeviceUser.STATUS_LINKED).exclude(
					pk=device_user.pk
				)
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

			queued = queue_commands(device, [build_delete_userinfo_command(device_uid)])

		publish_attendance_event(
			"fingerprint-deleted",
			{
				"device_user_id": device_user.id,
				"member_id": member.id if member else None,
				"device_uid": device_uid,
				"access_device_id": device.id,
			},
		)

		return Response(
			{
				"detail": "Device user deleted.",
				"device_user_id": device_user.id,
				"queued_command_ids": [entry["id"] for entry in queued],
			}
		)


class BiometricDeviceProfileListAPIView(APIView):
	feature_key = "attendance.devices"
	permission_classes = [HasFeatureMethodPermission]

	def get(self, request):
		data = [
			{
				"key": profile.key,
				"label": profile.label,
				"manufacturer": profile.manufacturer,
				"supports_remote_enroll": profile.supports_remote_enroll,
				"supports_fingerprint": profile.supports_fingerprint,
				"supports_card": profile.supports_card,
				"max_users": profile.max_users,
				"max_fingers_per_user": profile.max_fingers_per_user,
			}
			for profile in list_device_profiles()
		]
		return Response(data)


class FingerprintEnrollmentStartAPIView(APIView):
	feature_key = "attendance.fingerprints"
	method_permission_map = {"POST": "edit"}
	permission_classes = [HasFeatureMethodPermission]

	def post(self, request):
		serializer = FingerprintEnrollmentStartSerializer(data=request.data)
		serializer.is_valid(raise_exception=True)
		member = serializer.validated_data["member"]
		device = serializer.validated_data["device"]

		members_qs = Member.objects.filter(id=member.id)
		members_qs = scope_queryset_by_branch_access(
			members_qs,
			request.user,
			branch_field="branch_id",
		)
		if not members_qs.exists():
			return Response({"detail": "Member not found or not accessible."}, status=status.HTTP_404_NOT_FOUND)

		try:
			session = FingerprintEnrollmentService.start_enrollment(
				member=member,
				device=device,
				user=request.user,
				fingerprint_slot=serializer.validated_data.get("fingerprint_slot", 0),
			)
		except EnrollmentNotSupported as exc:
			return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
		except EnrollmentConflict as exc:
			return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
		except EnrollmentServiceError as exc:
			return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

		return Response(
			FingerprintEnrollmentSessionSerializer(session).data,
			status=status.HTTP_201_CREATED,
		)


class FingerprintEnrollmentDetailAPIView(APIView):
	feature_key = "attendance.fingerprints"
	permission_classes = [HasFeatureMethodPermission]

	def get(self, request, pk):
		session = get_object_or_404(
			FingerprintEnrollmentSession.objects.select_related("member", "access_device"),
			pk=pk,
		)
		FingerprintEnrollmentService.expire_if_needed(session)
		session.refresh_from_db()
		return Response(FingerprintEnrollmentSessionSerializer(session).data)


class FingerprintEnrollmentCancelAPIView(APIView):
	feature_key = "attendance.fingerprints"
	method_permission_map = {"POST": "edit"}
	permission_classes = [HasFeatureMethodPermission]

	def post(self, request, pk):
		session = get_object_or_404(FingerprintEnrollmentSession, pk=pk)
		session = FingerprintEnrollmentService.cancel_enrollment(session)
		return Response(FingerprintEnrollmentSessionSerializer(session).data)


class CardProvisionAPIView(APIView):
	feature_key = "attendance.fingerprints"
	method_permission_map = {"POST": "edit"}
	permission_classes = [HasFeatureMethodPermission]

	def post(self, request):
		serializer = CardProvisionSerializer(data=request.data)
		serializer.is_valid(raise_exception=True)
		member = serializer.validated_data["member"]
		device = serializer.validated_data["device"]

		members_qs = Member.objects.filter(id=member.id)
		members_qs = scope_queryset_by_branch_access(
			members_qs,
			request.user,
			branch_field="branch_id",
		)
		if not members_qs.exists():
			return Response({"detail": "Member not found or not accessible."}, status=status.HTTP_404_NOT_FOUND)

		try:
			result = CardProvisionService.provision(
				member=member,
				device=device,
				user=request.user,
			)
		except EnrollmentNotSupported as exc:
			return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
		except EnrollmentServiceError as exc:
			return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

		publish_attendance_event(
			"card-provisioned",
			{
				"member_id": member.id,
				"member_name": member.full_name,
				"access_device_id": device.id,
				"device_uid": result["device_uid"],
				"card_id": result["card_id"],
				"device_user_id": result["device_user_id"],
			},
		)
		return Response(
			{
				"detail": "Card provision queued.",
				**{k: v for k, v in result.items() if k != "queued_commands"},
				"queued_command_ids": [c["id"] for c in result["queued_commands"]],
			},
			status=status.HTTP_201_CREATED,
		)


class PublicSchemaADMSDispatchMixin:
	def _device_sn_from_request(self, request) -> str:
		params = getattr(request, "query_params", request.GET)
		return (params.get("SN") or "").strip()

	def _resolve_public_route(self, device_sn: str):
		if not device_sn:
			return None
		route = (
			AccessDeviceRoute.objects.select_related("tenant")
			.filter(
				device_sn=device_sn,
			)
			.first()
		)
		if route and route.is_active and route.tenant.is_enabled and route.tenant.status in Tenant.ENTRY_ALLOWED_STATUSES:
			return route
		return self._backfill_public_route(device_sn)

	def _backfill_public_route(self, device_sn: str):
		matches = []
		for tenant in (
			Tenant.objects.filter(
				is_enabled=True,
				status__in=Tenant.ENTRY_ALLOWED_STATUSES,
			)
			.exclude(schema_name=get_public_schema_name())
			.only("id", "schema_name")
		):
			with schema_context(tenant.schema_name):
				device_id = (
					AccessDevice.objects.filter(device_sn=device_sn, is_active=True)
					.values_list("id", flat=True)
					.first()
				)
			if device_id:
				matches.append((tenant, device_id))

		if not matches:
			return None

		if len(matches) > 1:
			logger.error(
				"[ADMS] PUBLIC_ROUTE ambiguous SN=%s across tenants=%s",
				device_sn,
				[t.schema_name for t, _ in matches],
			)
			return None

		tenant, device_id = matches[0]
		route, _ = AccessDeviceRoute.objects.update_or_create(
			tenant=tenant,
			access_device_id=device_id,
			defaults={
				"device_sn": device_sn,
				"is_active": True,
			},
		)
		return route

	def handle_public_schema_unknown_device(self, request, device_sn: str):
		raise NotImplementedError

	def dispatch(self, request, *args, **kwargs):
		if connection.schema_name != get_public_schema_name():
			return super().dispatch(request, *args, **kwargs)

		device_sn = self._device_sn_from_request(request)
		route = self._resolve_public_route(device_sn)
		if route is None:
			return self.handle_public_schema_unknown_device(request, device_sn)

		logger.info(
			"[ADMS] PUBLIC_ROUTE SN=%s -> tenant=%s",
			device_sn,
			route.tenant.schema_name,
		)
		with schema_context(route.tenant.schema_name):
			request.tenant = route.tenant
			return super().dispatch(request, *args, **kwargs)


class IclockCdataAPIView(PublicSchemaADMSDispatchMixin, APIView):
	"""ADMS iClock ingress endpoint scoped by known active device serial."""

	permission_classes = [AllowAny]

	def handle_public_schema_unknown_device(self, request, device_sn: str):
		client_ip = request.META.get("HTTP_X_FORWARDED_FOR", request.META.get("REMOTE_ADDR", "?"))
		logger.warning("[ADMS] PUBLIC_ROUTE rejected: unknown or inactive SN=%s from %s", device_sn, client_ip)
		return PlainTextResponse("ERR\n", status=404, content_type="text/plain; charset=UTF-8")

	def get(self, request):
		device_sn = (request.query_params.get("SN") or "").strip()
		client_ip = request.META.get("HTTP_X_FORWARDED_FOR", request.META.get("REMOTE_ADDR", "?"))
		logger.info("[ADMS] HEARTBEAT SN=%s from %s", device_sn, client_ip)
		device = AccessDevice.objects.filter(device_sn=device_sn, is_active=True).first()
		if not device:
			logger.warning("[ADMS] HEARTBEAT rejected: unknown or inactive SN=%s", device_sn)
			return PlainTextResponse("ERR\n", status=404, content_type="text/plain; charset=UTF-8")

		device.last_seen_at = timezone.now()
		device.status = AccessDevice.STATUS_ONLINE
		device.save(update_fields=["last_seen_at", "status", "updated_at"])

		meta = dict(device.meta_json or {})
		options = (request.query_params.get("options") or "").strip().lower()
		push_init = options == "all" or not meta.get("push_handshake_completed_at")

		try:
			tz = ZoneInfo(device.timezone or "Asia/Dhaka")
		except ZoneInfoNotFoundError:
			tz = ZoneInfo("UTC")
		now = timezone.now().astimezone(tz)
		date_str = now.strftime("%Y-%m-%d %H:%M:%S")

		if push_init:
			meta["push_handshake_completed_at"] = timezone.now().isoformat()
			device.meta_json = meta
			device.save(update_fields=["meta_json", "updated_at"])
			body = build_push_handshake_body(device)
			return PlainTextResponse(body, content_type="text/plain; charset=UTF-8")

		body = (
			"OK\n"
			f"Date:{date_str}\n"
			"GET_OPTION:ATTLOGStamp=0\n"
			"GET_OPTION:OPERLOGStamp=0\n"
			"GET_OPTION:USERINFOStamp=0\n"
			"GET_OPTION:ATTPHOTOStamp=0\n"
		)
		return PlainTextResponse(body, content_type="text/plain; charset=UTF-8")

	def post(self, request):
		device_sn = (request.query_params.get("SN") or "").strip()
		table_name = (request.query_params.get("table") or "").strip()
		client_ip = request.META.get("HTTP_X_FORWARDED_FOR", request.META.get("REMOTE_ADDR", "?"))
		device = AccessDevice.objects.filter(device_sn=device_sn, is_active=True).first()
		if not device:
			logger.warning("[ADMS] PUSH rejected: unknown or inactive SN=%s from %s", device_sn, client_ip)
			return PlainTextResponse("ERR\n", status=404, content_type="text/plain; charset=UTF-8")

		raw_body = request.body.decode("utf-8", errors="replace") if request.body else ""
		logger.info("[ADMS] PUSH SN=%s table=%s from %s body_len=%d", device_sn, table_name or "(none)", client_ip, len(raw_body))
		if raw_body:
			logger.debug("[ADMS] PUSH body:\n%s", raw_body[:2000])
		device.last_seen_at = timezone.now()
		device.status = AccessDevice.STATUS_ONLINE
		meta = dict(device.meta_json or {})
		meta["last_iclock_payload_at"] = timezone.now().isoformat()
		if raw_body:
			meta["last_iclock_payload_size"] = len(raw_body)
		device.meta_json = meta
		device.save(update_fields=["last_seen_at", "status", "meta_json", "updated_at"])
		summary = ADMSIngestionService.process(device, raw_body, table_hint=table_name)
		logger.info("[ADMS] PUSH SN=%s ingested: handled=%d skipped=%d total=%d",
					device_sn, summary['handled'], summary['skipped'], summary['total'])

		return PlainTextResponse(
			f"OK\nhandled={summary['handled']}\nskipped={summary['skipped']}\n",
			content_type="text/plain; charset=UTF-8",
		)


class IclockGetRequestAPIView(PublicSchemaADMSDispatchMixin, APIView):
	permission_classes = [AllowAny]

	def handle_public_schema_unknown_device(self, request, device_sn: str):
		client_ip = request.META.get("HTTP_X_FORWARDED_FOR", request.META.get("REMOTE_ADDR", "?"))
		logger.warning("[ADMS] PUBLIC_ROUTE GETREQUEST unknown SN=%s from %s", device_sn, client_ip)
		return PlainTextResponse("OK\n", content_type="text/plain; charset=UTF-8")

	def get(self, request):
		device_sn = (request.query_params.get("SN") or "").strip()
		client_ip = request.META.get("HTTP_X_FORWARDED_FOR", request.META.get("REMOTE_ADDR", "?"))
		device = AccessDevice.objects.filter(device_sn=device_sn, is_active=True).first()
		if not device:
			logger.warning("[ADMS] GETREQUEST unknown SN=%s from %s", device_sn, client_ip)
			return PlainTextResponse("OK\n", content_type="text/plain; charset=UTF-8")

		meta = dict(device.meta_json or {})

		device.last_seen_at = timezone.now()
		device.status = AccessDevice.STATUS_ONLINE

		next_cmd = dequeue_next_command(device)
		if next_cmd:
			if next_cmd.get("session_id") is not None:
				meta = dict(device.meta_json or {})
				meta["last_command_session_id"] = next_cmd["session_id"]
				device.meta_json = meta
			device.save(update_fields=["last_seen_at", "status", "meta_json", "updated_at"])
			cmd_str = f"C:{next_cmd['id']}:{next_cmd['cmd']}"
			logger.info("[ADMS] GETREQUEST SN=%s from %s -> dispatching: %s", device_sn, client_ip, cmd_str)
			return PlainTextResponse(
				f"{cmd_str}\n",
				content_type="text/plain; charset=UTF-8",
			)

		logger.info("[ADMS] GETREQUEST SN=%s from %s -> OK (no pending commands)", device_sn, client_ip)
		device.meta_json = meta
		device.save(update_fields=["last_seen_at", "status", "meta_json", "updated_at"])
		return PlainTextResponse("OK\n", content_type="text/plain; charset=UTF-8")


class IclockDeviceCmdAPIView(PublicSchemaADMSDispatchMixin, APIView):
	"""Device acknowledges a completed server command via POST to this endpoint."""

	permission_classes = [AllowAny]

	def handle_public_schema_unknown_device(self, request, device_sn: str):
		client_ip = request.META.get("HTTP_X_FORWARDED_FOR", request.META.get("REMOTE_ADDR", "?"))
		logger.warning("[ADMS] PUBLIC_ROUTE CMD_ACK unknown SN=%s from %s", device_sn, client_ip)
		return PlainTextResponse("OK\n", content_type="text/plain; charset=UTF-8")

	def post(self, request):
		device_sn = (request.query_params.get("SN") or "").strip()
		client_ip = request.META.get("HTTP_X_FORWARDED_FOR", request.META.get("REMOTE_ADDR", "?"))
		device = AccessDevice.objects.filter(device_sn=device_sn, is_active=True).first()
		if device:
			raw = request.body.decode("utf-8", errors="replace") if request.body else ""
			logger.info("[ADMS] CMD_ACK SN=%s from %s body=%s", device_sn, client_ip, raw[:200] if raw else "(empty)")
			parsed = parse_devicecmd_body(raw)
			meta = dict(device.meta_json or {})
			meta["last_cmd_ack_at"] = timezone.now().isoformat()
			if raw:
				meta["last_cmd_ack_body"] = raw[:500]
			if parsed:
				meta["last_cmd_ack_parsed"] = parsed
			device.last_seen_at = timezone.now()
			device.status = AccessDevice.STATUS_ONLINE
			device.meta_json = meta
			device.save(update_fields=["last_seen_at", "status", "meta_json", "updated_at"])

			command_id = parsed.get("ID", "")
			return_code_raw = parsed.get("Return", "0")
			cmd_echo = parsed.get("CMD", "")
			try:
				return_code = int(return_code_raw)
			except (TypeError, ValueError):
				return_code = -1

			if command_id:
				lookup_queued_command(device, command_id)
				FingerprintEnrollmentService.handle_command_ack(
					device=device,
					command_id=command_id,
					return_code=return_code,
					cmd_echo=cmd_echo,
				)
		return PlainTextResponse("OK\n", content_type="text/plain; charset=UTF-8")


class DeviceCredentialRotateAPIView(APIView):
	feature_key = "attendance.devices"
	method_permission_map = {"POST": "edit"}
	permission_classes = [HasFeatureMethodPermission]

	def post(self, request, pk):
		device = get_object_or_404(AccessDevice, pk=pk)
		serializer = DeviceCredentialRotateSerializer(data=request.data)
		serializer.is_valid(raise_exception=True)

		secret_hash = hashlib.sha256(serializer.validated_data["secret"].encode("utf-8")).hexdigest()
		obj, _ = DeviceCredential.objects.update_or_create(
			access_device=device,
			key=serializer.validated_data["key"],
			defaults={"secret_ciphertext": secret_hash, "is_active": True},
		)
		return Response({
			"detail": "Credential updated.",
			"device_id": device.id,
			"key": obj.key,
			"rotated_at": obj.rotated_at,
		})
