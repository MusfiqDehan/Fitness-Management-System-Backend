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
from utils.tenancy_helpers import scope_queryset_by_branch_access
from .models import AccessDevice, AttendanceIngestEvent, DeviceCredential, DeviceUser

logger = logging.getLogger(__name__)
from .services.ingestion import ADMSIngestionService
from .services.realtime import publish_attendance_event
from .serializers import (
	AccessDeviceSerializer,
	AttendanceLogSerializer,
	DeviceCredentialRotateSerializer,
	DeviceUserSerializer,
	FingerprintLinkSerializer,
	FingerprintUnlinkSerializer,
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

		# If member is already inside, next valid scan closes the session.
		open_attendance = Attendance.objects.filter(
			member=member,
			check_out_time__isnull=True,
		).first()
		if open_attendance:
			open_attendance.check_out_time = timezone.now()
			open_attendance.save(update_fields=["check_out_time"])
			publish_attendance_event(
				"attendance-updated",
				{
					"member_id": member.id,
					"member_name": member.full_name,
					"action": "checked_out",
					"device_sn": access_device.device_sn if access_device else device_id,
				},
			)
			return Response(
				{
					"access": True,
					"action": "checked_out",
					"member_name": member.full_name,
				}
			)

		# Keep anti-duplicate tap protection during migration window.
		last_entry = Attendance.objects.filter(member=member).order_by("-check_in_time").first()
		if last_entry:
			time_diff = timezone.now() - last_entry.check_in_time
			if time_diff < timedelta(seconds=20):
				return Response(
					{"access": False, "message": "Duplicate scan detected"},
					status=status.HTTP_409_CONFLICT,
				)

		Attendance.objects.create(
			member=member,
			entry_method="card" if card_id else "fingerprint",
			device_id=device_id or (access_device.device_sn if access_device else None),
		)
		publish_attendance_event(
			"attendance-updated",
			{
				"member_id": member.id,
				"member_name": member.full_name,
				"action": "checked_in",
				"device_sn": access_device.device_sn if access_device else device_id,
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
	try:
		device_tz = ZoneInfo(device.timezone or "Asia/Dhaka")
	except ZoneInfoNotFoundError:
		device_tz = ZoneInfo("UTC")

	latest_attlog = (
		AttendanceIngestEvent.objects.filter(
			access_device=device,
			event_type="ATTLOG",
			event_time__isnull=False,
		)
		.order_by("-event_time")
		.first()
	)

	if latest_attlog and latest_attlog.event_time:
		start_time = latest_attlog.event_time.astimezone(device_tz) - timedelta(minutes=1)
	else:
		# Avoid full-history backfills on first manual sync. Devices still push new
		# scans in real time, so a short window is enough for operational retries.
		start_time = timezone.now().astimezone(device_tz) - timedelta(minutes=5)

	formatted = start_time.strftime("%Y-%m-%d %H:%M:%S")
	return f"DATA QUERY ATTLOG StartTime={formatted}", formatted


class DeviceSyncNowAPIView(_DeviceActionBaseAPIView):
	def post(self, request, pk):
		device = self.get_object(pk)
		meta = dict(device.meta_json or {})
		meta["last_sync_requested_at"] = timezone.now().isoformat()
		attlog_command, attlog_start_time = _build_attlog_sync_command(device)
		# Queue ADMS commands the device will pick up on its next getrequest poll.
		# C:<id>:<command> is the ADMS server-push command format.
		# DATA QUERY USERINFO  — device uploads all enrolled users / fingerprints.
		# DATA QUERY ATTLOG    — device uploads only recent attendance logs.
		meta["pending_commands"] = [
			{"id": 1, "cmd": "DATA QUERY USERINFO"},
			{"id": 2, "cmd": attlog_command},
		]
		device.meta_json = meta
		device.save(update_fields=["meta_json", "updated_at"])
		return Response({
			"detail": "Device sync queued. Commands will be sent on next device poll.",
			"id": device.id,
			"last_sync_requested_at": meta["last_sync_requested_at"],
			"attlog_start_time": attlog_start_time,
			"commands_queued": len(meta["pending_commands"]),
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


class FingerprintUnlinkedListAPIView(ListAPIView):
	feature_key = "attendance.fingerprints"
	permission_classes = [HasFeatureMethodPermission]
	serializer_class = DeviceUserSerializer

	def get_queryset(self):
		queryset = DeviceUser.objects.filter(status=DeviceUser.STATUS_UNLINKED).select_related("member", "access_device")
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

			# Backward-compatible sync with legacy membership fingerprint identity.
			member.fingerprint_id = device_user.device_uid
			member.save(update_fields=["fingerprint_id"])

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

		with transaction.atomic():
			device_user.member = None
			device_user.status = DeviceUser.STATUS_UNLINKED
			device_user.save(update_fields=["member", "status", "last_seen_at"])

			if member and member.fingerprint_id == device_user.device_uid:
				member.fingerprint_id = None
				member.save(update_fields=["fingerprint_id"])

		publish_attendance_event(
			"fingerprint-unlinked",
			{
				"device_user_id": device_user.id,
				"member_id": member.id if member else None,
			},
		)

		return Response({"detail": "Fingerprint unlinked.", "device_user_id": device_user.id})


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

		try:
			tz = ZoneInfo(device.timezone or "Asia/Dhaka")
		except ZoneInfoNotFoundError:
			tz = ZoneInfo("UTC")
		now = timezone.now().astimezone(tz)
		date_str = now.strftime("%Y-%m-%d %H:%M:%S")
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
		pending = list(meta.get("pending_commands", []))

		device.last_seen_at = timezone.now()
		device.status = AccessDevice.STATUS_ONLINE

		if pending:
			# Dequeue the next command and send it to the device.
			next_cmd = pending.pop(0)
			meta["pending_commands"] = pending
			meta["last_command_sent"] = next_cmd["cmd"]
			meta["last_command_sent_at"] = timezone.now().isoformat()
			device.meta_json = meta
			device.save(update_fields=["last_seen_at", "status", "meta_json", "updated_at"])
			# ADMS command format: C:<id>:<command>
			cmd_str = f"C:{next_cmd['id']}:{next_cmd['cmd']}"
			logger.info("[ADMS] GETREQUEST SN=%s from %s -> dispatching: %s", device_sn, client_ip, cmd_str)
			return PlainTextResponse(
				f"{cmd_str}\n",
				content_type="text/plain; charset=UTF-8",
			)

		logger.info("[ADMS] GETREQUEST SN=%s from %s -> OK (no pending commands)", device_sn, client_ip)
		device.meta_json = meta
		device.save(update_fields=["last_seen_at", "status", "updated_at"])
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
			meta = dict(device.meta_json or {})
			meta["last_cmd_ack_at"] = timezone.now().isoformat()
			if raw:
				meta["last_cmd_ack_body"] = raw[:500]  # cap stored size
			device.last_seen_at = timezone.now()
			device.status = AccessDevice.STATUS_ONLINE
			device.meta_json = meta
			device.save(update_fields=["last_seen_at", "status", "meta_json", "updated_at"])
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
