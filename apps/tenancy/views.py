from datetime import date, datetime, time, timedelta
import hashlib
import logging
import secrets
from urllib.parse import quote

from django.conf import settings
from django.core.cache import cache
from django.core.mail import EmailMultiAlternatives
from django.db import transaction, connection
from django.db.utils import DatabaseError
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.text import slugify
from django_tenants.utils import get_public_schema_name, schema_context
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated, BasePermission
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
# from utils.throttling import (
# 	BurstAnonRateThrottle,
# 	BurstUserRateThrottle,
# 	SustainedAnonRateThrottle,
# 	SustainedUserRateThrottle,
# )
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from utils.cache_helpers import (
    TENANT_OVERVIEW_TTL,
    get_cached_value,
    invalidate_user_permissions,
    tenant_overview_key,
)
from apps.crm.email_delivery import resolve_operational_mail_route, resolve_platform_mail_route
from apps.identity.models import User
from .models import Tenant, Domain, Invitation, EmailQueue, TenantAuditLog, PaymentGateway, PlatformPackage, PlatformSettings
from .permissions import IsPlatformFeaturePermission
from .serializers import (
	TenantSelfRegistrationSerializer,
	InvitationTokenSerializer,
	PasswordSetupSerializer,
	TenantAuthSerializer,
	PasswordResetRequestSerializer,
	TenantStatusSerializer,
	TenantListSerializer,
	TenantUpdateSerializer,
	SuperadminInvitationSerializer,
	PlatformSettingsSerializer,
	TenantAdminInvitationListSerializer,
	full_domain_for_subdomain,
)
from .services import normalize_plan_slug
from utils.query_optimization import build_tenant_admins_map


logger = logging.getLogger(__name__)


def _is_superadmin(user):
	return bool(
		user
		and user.is_authenticated
		and (user.is_superuser or getattr(user, "role", "") == "superuser")
	)


def _is_public_platform_user(user):
	public_schema = get_public_schema_name()
	user_tenant_schema = getattr(getattr(user, "tenant", None), "schema_name", None)
	return _is_superadmin(user) and user_tenant_schema == public_schema


def _is_public_schema_request(request):
	request_tenant = getattr(request, "tenant", None)
	request_schema = getattr(request_tenant, "schema_name", None) or connection.schema_name
	return request_schema == get_public_schema_name()


class IsPlatformSuperAdmin(BasePermission):
	def has_permission(self, request, view):
		return _is_public_schema_request(request) and _is_public_platform_user(request.user)


def _record_audit(request, action, tenant=None, target_type="", target_id="", metadata=None):
	TenantAuditLog.objects.create(
		tenant=tenant,
		actor_email=(getattr(request.user, "email", "") or "") if request.user.is_authenticated else "",
		actor_id=getattr(request.user, "id", None) if request.user.is_authenticated else None,
		action=action,
		target_type=target_type,
		target_id=str(target_id or ""),
		ip_address=request.META.get("REMOTE_ADDR") if request else None,
		user_agent=(request.META.get("HTTP_USER_AGENT", "") if request else ""),
		metadata=_json_safe(metadata or {}),
	)


def _json_safe(value):
	if isinstance(value, dict):
		return {str(key): _json_safe(item) for key, item in value.items()}
	if isinstance(value, (list, tuple, set)):
		return [_json_safe(item) for item in value]
	if isinstance(value, (datetime, date, time)):
		return value.isoformat()
	if isinstance(value, timedelta):
		return value.total_seconds()
	return value


def _issue_email(
	*,
	tenant,
	to_email,
	purpose,
	subject,
	template_name,
	context,
	fallback_text,
	mail_route="operational",
):
	safe_context = _json_safe(context or {})
	html_body = render_to_string(template_name, context)
	mail_log = EmailQueue.objects.create(
		tenant=tenant,
		to_email=to_email,
		subject=subject,
		html_body=html_body,
		text_body=fallback_text,
		purpose=purpose,
		context=safe_context,
	)

	if mail_route == "platform":
		from_email, connection, _ = resolve_platform_mail_route()
	else:
		from_email, connection = resolve_operational_mail_route(tenant)
	email = EmailMultiAlternatives(
		subject=subject,
		body=fallback_text,
		from_email=from_email,
		to=[to_email],
		connection=connection,
	)
	email.attach_alternative(html_body, "text/html")

	try:
		email.send(fail_silently=False)
	except Exception as first_exc:
		fallback_from, fallback_connection, _ = resolve_platform_mail_route()
		if not fallback_from:
			fallback_from = getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@gym.local")
		fallback_email = EmailMultiAlternatives(
			subject=subject,
			body=fallback_text,
			from_email=fallback_from,
			to=[to_email],
			connection=fallback_connection,
		)
		fallback_email.attach_alternative(html_body, "text/html")
		try:
			fallback_email.send(fail_silently=False)
		except Exception as exc:
			env_fallback = EmailMultiAlternatives(
				subject=subject,
				body=fallback_text,
				from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@gym.local"),
				to=[to_email],
			)
			env_fallback.attach_alternative(html_body, "text/html")
			try:
				env_fallback.send(fail_silently=False)
			except Exception as env_exc:
				mail_log.status = EmailQueue.STATUS_FAILED
				mail_log.attempts += 1
				mail_log.last_error = f"primary={first_exc}; platform={exc}; env={env_exc}"
				mail_log.save(update_fields=["status", "attempts", "last_error"])
				return

		mail_log.status = EmailQueue.STATUS_SENT
		mail_log.sent_at = timezone.now()
		mail_log.attempts += 1
		mail_log.save(update_fields=["status", "sent_at", "attempts"])
		return

	mail_log.status = EmailQueue.STATUS_SENT
	mail_log.sent_at = timezone.now()
	mail_log.attempts += 1
	mail_log.save(update_fields=["status", "sent_at", "attempts"])


def _derive_schema_name(subdomain):
	return subdomain.replace("-", "_")


def _request_host(request):
	if request is None:
		return ""
	return request.get_host().split(":")[0].strip().lower()


def _public_request_hosts():
	public_domain = getattr(settings, "PUBLIC_DOMAIN", "").strip().lower()
	return {
		host
		for host in {
			public_domain,
			f"www.{public_domain}" if public_domain else "",
			"localhost",
			"127.0.0.1",
			"testserver",
		}
		if host
	}


def _tenant_frontend_host(*, subdomain="", domain=""):
	configured_base_domain = getattr(settings, "TENANT_FRONTEND_BASE_DOMAIN", "").strip().lower()
	if subdomain and configured_base_domain:
		if configured_base_domain in {"localhost", "127.0.0.1"}:
			return f"{subdomain}.localhost"
		return f"{subdomain}.{configured_base_domain}"
	return (domain or "").strip().lower()


def _resolve_invitation_domain(invitation):
	metadata = invitation.metadata or {}
	domain = (metadata.get("domain") or "").strip().lower()
	if domain:
		return domain
	if invitation.tenant_id:
		domain = invitation.tenant.domains.filter(is_primary=True).values_list("domain", flat=True).first()
		if domain:
			return domain.strip().lower()
	return full_domain_for_subdomain(invitation.subdomain)


def _assert_token_request_scope(request, invitation):
	expected_domain = _resolve_invitation_domain(invitation)
	request_host = _request_host(request)
	if request_host and request_host not in _public_request_hosts() and request_host != expected_domain:
		raise ValidationError({"detail": "Token does not belong to this tenant domain."})
	return expected_domain


def _sync_tenant_dashboard_settings(*, tenant_id, schema_name, timezone_value=None, locale_value=None):
	"""Sync platform-side tenant edits into tenant-schema dashboard settings.

	This keeps public-schema Tenant.timezone/locale aligned with tenant-local
	GymProfile.timezone and GymPreferences.language, which are read by existing
	tenant APIs and frontend hooks.
	"""
	public_schema = get_public_schema_name()
	if not schema_name or schema_name == public_schema:
		return

	try:
		with schema_context(schema_name):
			from apps.dashboard.models import GymProfile, GymPreferences

			if timezone_value:
				profile, _ = GymProfile.objects.get_or_create(pk=1)
				if profile.timezone != timezone_value:
					profile.timezone = timezone_value
					profile.save(update_fields=["timezone", "updated_at"])

			if locale_value:
				prefs, _ = GymPreferences.objects.get_or_create(pk=1)
				if prefs.language != locale_value:
					prefs.language = locale_value
					prefs.save(update_fields=["language", "updated_at"])
	except Exception:
		logger.exception(
			"Failed to sync tenant dashboard settings",
			extra={"tenant_id": tenant_id, "schema_name": schema_name},
		)


def _propagate_platform_default_language(*, old_language, new_language):
	"""Apply a new platform default language to tenants still on the old default."""
	if not old_language or not new_language or old_language == new_language:
		return

	public_schema = get_public_schema_name()
	with schema_context(public_schema):
		tenant_rows = list(
			Tenant.objects
			.exclude(schema_name=public_schema)
			.filter(locale=old_language)
			.values_list("id", "schema_name")
		)
		tenant_ids = [tenant_id for tenant_id, _ in tenant_rows]
		if tenant_ids:
			Tenant.objects.filter(id__in=tenant_ids).update(locale=new_language)

	for tenant_id, schema_name in tenant_rows:
		_sync_tenant_dashboard_settings(
			tenant_id=tenant_id,
			schema_name=schema_name,
			locale_value=new_language,
		)


def _get_package_trial_days(plan_slug: str) -> int:
	"""Return trial_days from PlatformPackage, defaulting to 14 if not found."""
	resolved_plan_slug = normalize_plan_slug(plan_slug)
	if not resolved_plan_slug:
		return 14
	public_schema = get_public_schema_name()
	with schema_context(public_schema):
		pkg = PlatformPackage.objects.filter(slug=resolved_plan_slug, is_active=True).first()
		if pkg:
			return max(0, pkg.trial_days)
	return 14


def _get_package_limits(plan_slug: str) -> dict:
	"""Return package capacity limits for a plan, with safe defaults."""
	resolved_plan_slug = normalize_plan_slug(plan_slug)
	if not resolved_plan_slug:
		return {
			"max_users": 10,
			"max_branches": 1,
			"max_members_per_branch": 0,
			"max_trainers_per_branch": 0,
		}

	public_schema = get_public_schema_name()
	with schema_context(public_schema):
		pkg = PlatformPackage.objects.filter(slug=resolved_plan_slug, is_active=True).first()
		if pkg:
			return {
				"max_users": int(pkg.max_users or 0),
				"max_branches": int(pkg.max_branches or 0),
				"max_members_per_branch": int(getattr(pkg, "max_members_per_branch", 0) or 0),
				"max_trainers_per_branch": int(getattr(pkg, "max_trainers_per_branch", 0) or 0),
			}

	return {
		"max_users": 10,
		"max_branches": 1,
		"max_members_per_branch": 0,
		"max_trainers_per_branch": 0,
	}


def _maybe_initiate_subscription_payment(
	tenant,
	plan_slug: str,
	request,
	*,
	contact_phone: str = "",
	contact_email: str = "",
	contact_name: str = "",
) -> dict:
	"""Initiate a SaaS subscription payment for a newly created tenant.

	Returns a dict with `payment_url` (str or None) and `trial_days` (int).
	Only initiates payment when:
	  - The package has price_monthly > 0
	  - The package has trial_days == 0 (no free trial)
	  - The platform has a default gateway with credentials configured

	When trial_days > 0, no payment is initiated — the tenant is billed
	after the trial period ends (via a separate renewal flow).
	"""
	public_schema = get_public_schema_name()
	with schema_context(public_schema):
		pkg = PlatformPackage.objects.filter(slug=plan_slug, is_active=True).first()
		if pkg is None:
			return {"payment_url": None, "trial_days": 14, "is_trial": True}

		trial_days = max(0, pkg.trial_days)

		if trial_days > 0:
			# Free trial — no immediate payment required
			return {"payment_url": None, "trial_days": trial_days, "is_trial": True}

		from decimal import Decimal
		if pkg.price_monthly <= Decimal("0"):
			# Free plan — no charge
			return {"payment_url": None, "trial_days": 0, "is_trial": False}

		# Paid plan with no trial — initiate payment now
		gateway = PaymentGateway.objects.filter(
			is_default_for_subscriptions=True,
		).first()
		if gateway is None or not (gateway.platform_credentials or {}):
			# No gateway configured yet — let them in anyway (admin can collect payment manually)
			return {"payment_url": None, "trial_days": 0, "is_trial": False}

		from apps.billing.services import get_gateway
		from apps.tenancy.models import TenantSubscriptionInvoice, PlatformSettings
		from utils.currency import convert_currency
		import uuid as _uuid

		# Determine the currency dynamically
		# System currency -> PlatformSettings.default_currency, otherwise fallback to "BDT" or "USD"
		ps = PlatformSettings.objects.filter(pk=1).first()
		target_currency = ps.default_currency if ps else "USD"

		# Package price is defined in USD. Let's convert to target currency
		original_amount = pkg.price_monthly
		converted_amount = convert_currency(original_amount, "USD", target_currency)

		tran_id = f"SUB-{tenant.schema_name.upper()}-{_uuid.uuid4().hex[:12].upper()}"
		backend_base = getattr(settings, "BACKEND_BASE_URL", request.build_absolute_uri("/").rstrip("/"))
		invoice = TenantSubscriptionInvoice.objects.create(
			tenant=tenant,
			package_slug=pkg.slug,
			package_name=pkg.name,
			amount=converted_amount,
			currency=target_currency,
			tran_id=tran_id,
			gateway_slug=gateway.slug,
			status=TenantSubscriptionInvoice.STATUS_PENDING,
			period_start=timezone.now(),
			period_end=timezone.now() + timedelta(days=30),
			is_trial=False,
		)

		# Pass onboarding contact info to the gateway payload builder.
		# These are transient attributes used only for this initiate() call.
		invoice.customer_phone = (contact_phone or "").strip()
		invoice.customer_email = (contact_email or "").strip()
		invoice.customer_name = (contact_name or "").strip()

		try:
			svc = get_gateway(
				gateway.slug,
				credentials=gateway.platform_credentials,
				is_sandbox=gateway.is_sandbox,
				success_url=f"{backend_base}/api/v1/billing/subscription/success/",
				fail_url=f"{backend_base}/api/v1/billing/subscription/fail/",
				cancel_url=f"{backend_base}/api/v1/billing/subscription/cancel/",
				ipn_url=f"{backend_base}/api/v1/billing/subscription/ipn/",
			)
			result = svc.initiate(invoice)
			return {
				"payment_url": result.get("gateway_url"),
				"tran_id": tran_id,
				"trial_days": 0,
				"is_trial": False,
			}
		except Exception:
			# If payment initiation fails, don't block tenant creation; admin can follow up
			invoice.status = TenantSubscriptionInvoice.STATUS_FAILED
			invoice.save(update_fields=["status", "updated_at"])
			return {"payment_url": None, "trial_days": 0, "is_trial": False}


def _create_tenant_with_domains(
	*,
	company_name,
	subdomain,
	owner_email,
	custom_domain="",
	primary_domain="",
	max_users=10,
	max_branches=1,
	max_members_per_branch=0,
	max_trainers_per_branch=0,
	plan="starter",
):
	public_schema = get_public_schema_name()
	with schema_context(public_schema):
		resolved_plan_slug = normalize_plan_slug(plan)
		platform_settings = PlatformSettings.objects.filter(pk=1).first()
		schema_name = _derive_schema_name(subdomain)
		if Tenant.objects.filter(schema_name=schema_name).exists():
			raise ValidationError({"subdomain": "This subdomain conflicts with an existing tenant schema."})

		slug_candidate = slugify(company_name)[:45] or subdomain
		code_candidate = (subdomain.replace("-", "") or "tenant")[:40].upper()

		unique_suffix = 1
		final_slug = slug_candidate
		while Tenant.objects.filter(slug=final_slug).exists():
			unique_suffix += 1
			final_slug = f"{slug_candidate}-{unique_suffix}"

		final_code = code_candidate
		while Tenant.objects.filter(code=final_code).exists():
			unique_suffix += 1
			final_code = f"{code_candidate}{unique_suffix}"

		tenant = Tenant.objects.create(
			schema_name=schema_name,
			name=company_name,
			slug=final_slug,
			code=final_code,
			owner_email=owner_email,
			billing_email=owner_email,
			timezone=(platform_settings.default_timezone if platform_settings else "Asia/Dhaka"),
			locale=(platform_settings.default_language if platform_settings else "en"),
			plan=resolved_plan_slug,
			status="trial",
			is_trial=True,
			trial_ends_at=timezone.now() + timedelta(days=_get_package_trial_days(resolved_plan_slug)),
			max_users=max_users,
			max_branches=max_branches,
			max_members_per_branch=max_members_per_branch,
			max_trainers_per_branch=max_trainers_per_branch,
			is_enabled=True,
		)

		domain = (primary_domain or full_domain_for_subdomain(subdomain)).strip().lower()
		if Domain.objects.filter(domain=domain).exists():
			raise ValidationError({"subdomain": "This subdomain is already in use."})
		Domain.objects.create(domain=domain, tenant=tenant, is_primary=True)

		if custom_domain:
			custom_domain = custom_domain.strip().lower()
			if Domain.objects.filter(domain=custom_domain).exists():
				raise ValidationError({"custom_domain": "This custom domain is already in use."})
			Domain.objects.create(domain=custom_domain, tenant=tenant, is_primary=False)

	return tenant, domain


def _bootstrap_tenant_branding_defaults(tenant):
	"""Initialize tenant-local branding records from the tenant company name."""
	with schema_context(tenant.schema_name):
		from apps.dashboard.models import GymProfile

		gym_profile, _ = GymProfile.objects.get_or_create(
			pk=1,
			defaults={"gym_name": tenant.name},
		)
		if not (gym_profile.gym_name or "").strip():
			gym_profile.gym_name = tenant.name
			gym_profile.save(update_fields=["gym_name"])


def _build_frontend_url(path_suffix, *, subdomain="", domain="", prefer_public=False):
	path = f"/{path_suffix.lstrip('/')}"
	if not prefer_public:
		host = _tenant_frontend_host(subdomain=subdomain, domain=domain)
		if host:
			scheme = getattr(settings, "TENANT_FRONTEND_SCHEME", "https").strip().lower() or "https"
			port = getattr(settings, "TENANT_FRONTEND_PORT", "").strip()
			netloc = host if not port else f"{host}:{port}"
			return f"{scheme}://{netloc}{path}"

	base = getattr(settings, "PUBLIC_FRONTEND_URL", "").strip() or getattr(settings, "FRONTEND_BASE_URL", "").strip()
	if base:
		return f"{base.rstrip('/')}{path}"
	return path


def _token_type_to_path(token_type):
	"""Map an Invitation.token_type value to the correct new-frontend route path."""
	return {
		"verification": "verify-email",
		"invitation": "accept-invite",
		"password_reset": "reset-password",
		"platform_invite": "accept-platform-invite",
	}.get(token_type, "accept-invite")


def _build_login_url(*, subdomain="", domain=""):
	return _build_frontend_url("/login", subdomain=subdomain, domain=domain)


def _prefer_public_onboarding_links():
	return bool(getattr(settings, "TENANT_ONBOARDING_LINKS_PUBLIC", False))


def _tenant_entry_is_allowed(tenant):
	return tenant is None or tenant.allows_user_entry()


def _tenant_entry_blocked_response():
	return Response({"detail": "Tenant workspace is suspended."}, status=status.HTTP_403_FORBIDDEN)


def _password_setup_success_response(invitation, *, domain, message="Password configured successfully.", payment_info=None):
	tenant = invitation.tenant
	data = {
		"message": message,
		"tenant_schema": tenant.schema_name if tenant else "",
		"tenant_domain": domain,
		"login_url": _build_login_url(subdomain=invitation.subdomain, domain=domain),
	}
	if payment_info:
		data.update({
			"payment_required": bool(payment_info.get("payment_url")),
			"payment_url": payment_info.get("payment_url"),
			"tran_id": payment_info.get("tran_id"),
			"is_trial": payment_info.get("is_trial", True),
			"trial_days": payment_info.get("trial_days", 0),
			"trial_ends_at": (
				tenant.trial_ends_at.isoformat() if tenant and tenant.trial_ends_at else None
			),
		})
	return Response(data)


def _count_tenant_admin_users():
	count = 0
	public_schema = get_public_schema_name()
	for tenant in Tenant.objects.exclude(schema_name=public_schema).only("schema_name"):
		try:
			with schema_context(tenant.schema_name):
				count += User.objects.filter(role__in=["admin", "superuser"]).count()
		except DatabaseError:
			continue
	return count


class TenantSelfRegistrationAPIView(APIView):
	permission_classes = [AllowAny]
	throttle_classes = [
		# BurstAnonRateThrottle,
		# BurstUserRateThrottle,
		# SustainedAnonRateThrottle,
		# SustainedUserRateThrottle,
		ScopedRateThrottle,
	]
	throttle_scope = "tenant_registration"

	def post(self, request):
		serializer = TenantSelfRegistrationSerializer(data=request.data, context={"request": request})
		serializer.is_valid(raise_exception=True)
		payload = serializer.validated_data
		selected_plan = normalize_plan_slug(payload.get("plan"))
		selected_limits = _get_package_limits(selected_plan)

		domain = full_domain_for_subdomain(payload["subdomain"], request=request)
		with transaction.atomic():
			raw_token, invitation = Invitation.issue_token(
				token_type=Invitation.TOKEN_TYPE_VERIFICATION,
				email=payload["admin_email"],
				invitee_full_name=payload.get("admin_full_name", ""),
				subdomain=payload["subdomain"],
				company_name=payload["company_name"],
				ttl_minutes=120,
				metadata={
					"domain": domain,
					"plan": selected_plan,
						"max_users": selected_limits["max_users"],
						"max_branches": selected_limits["max_branches"],
						"max_members_per_branch": selected_limits["max_members_per_branch"],
						"max_trainers_per_branch": selected_limits["max_trainers_per_branch"],
					"contact_phone": payload.get("contact_phone", ""),
				},
			)

		setup_url = _build_frontend_url(
			f"/verify-email?token={quote(raw_token)}",
			subdomain=payload["subdomain"],
			domain=domain,
			prefer_public=_prefer_public_onboarding_links(),
		)
		_issue_email(
			tenant=None,
			to_email=payload["admin_email"],
			purpose=EmailQueue.PURPOSE_VERIFICATION,
			subject="Verify your tenant registration",
			template_name="tenancy/emails/verification_email.html",
			context={
				"company_name": payload["company_name"],
				"subdomain": payload["subdomain"],
				"verification_url": setup_url,
				"expires_at": invitation.expires_at,
			},
			fallback_text=f"Verify your registration by visiting {setup_url}",
			mail_route="platform",
		)

		return Response(
			{
				"message": "Registration received. Please check your email to verify and set password. Tenant will be created after password setup.",
				"pending_tenant": {
					"company_name": payload["company_name"],
					"subdomain": payload["subdomain"],
					"domain": domain,
				},
			},
			status=status.HTTP_201_CREATED,
		)


def _rotate_tenant_invitation_token(invitation):
	raw_token = secrets.token_urlsafe(32)
	invitation.token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
	invitation.expires_at = timezone.now() + timedelta(minutes=60 * 24)
	invitation.save(update_fields=["token_hash", "expires_at"])
	return raw_token


def _send_tenant_invitation_email(invitation, request, raw_token):
	domain_name = (invitation.metadata or {}).get("domain") or full_domain_for_subdomain(
		invitation.subdomain,
		request=request,
	)
	setup_url = _build_frontend_url(
		f"/accept-invite?token={quote(raw_token)}",
		subdomain=invitation.subdomain,
		domain=domain_name,
		prefer_public=_prefer_public_onboarding_links(),
	)
	_issue_email(
		tenant=invitation.tenant,
		to_email=invitation.email,
		purpose=EmailQueue.PURPOSE_INVITATION,
		subject="You have been invited to a tenant workspace",
		template_name="tenancy/emails/invitation_email.html",
		context={
			"company_name": invitation.company_name,
			"subdomain": invitation.subdomain,
			"invitation_url": setup_url,
			"expires_at": invitation.expires_at,
		},
		fallback_text=f"Accept your invitation by visiting {setup_url}",
		mail_route="platform",
	)
	return setup_url


class SuperadminInvitationAPIView(APIView):
	throttle_classes = [
		# BurstAnonRateThrottle,
		# BurstUserRateThrottle,
		# SustainedAnonRateThrottle,
		# SustainedUserRateThrottle,
		ScopedRateThrottle,
	]
	throttle_scope = "superadmin_invitation"

	def get_permissions(self):
		if self.request.method == "GET":
			return [IsPlatformFeaturePermission.require("platform.tenants", "view")()]
		return [IsPlatformFeaturePermission.require("platform.tenants", "edit")()]

	def get(self, request):
		with schema_context(get_public_schema_name()):
			invitations = (
				Invitation.objects.filter(
					token_type=Invitation.TOKEN_TYPE_INVITATION,
					used_at__isnull=True,
				)
				.order_by("-created_at")
			)
			data = TenantAdminInvitationListSerializer(invitations, many=True).data
		return Response(data)

	def post(self, request):
		serializer = SuperadminInvitationSerializer(
			data=request.data,
			context={"request": request, "allow_existing_subdomain": True},
		)
		serializer.is_valid(raise_exception=True)
		payload = serializer.validated_data

		domain_name = full_domain_for_subdomain(payload["subdomain"], request=request)
		public_schema = get_public_schema_name()

		with schema_context(public_schema):
			existing_domain = Domain.objects.select_related("tenant").filter(domain=domain_name).first()

		with transaction.atomic():
			if existing_domain is not None:
				tenant = existing_domain.tenant
				requested_email = payload["admin_email"].strip().lower()
				tenant_owner = (tenant.owner_email or "").strip().lower()
				if tenant_owner and tenant_owner != requested_email:
					raise ValidationError({"subdomain": "This subdomain is already in use."})

				if not tenant_owner:
					tenant.owner_email = requested_email
					tenant.billing_email = tenant.billing_email or requested_email
					tenant.save(update_fields=["owner_email", "billing_email", "updated_at"])

				raw_token, invitation = Invitation.issue_token(
					token_type=Invitation.TOKEN_TYPE_INVITATION,
					tenant=tenant,
					email=requested_email,
					invitee_full_name=payload.get("admin_full_name", ""),
					subdomain=payload["subdomain"],
					company_name=tenant.name,
					invited_by_email=getattr(request.user, "email", ""),
					ttl_minutes=60 * 24,
					metadata={"domain": domain_name, "resend": True},
				)

				setup_url = _build_frontend_url(
						f"/accept-invite?token={quote(raw_token)}",
					subdomain=payload["subdomain"],
					domain=domain_name,
					prefer_public=_prefer_public_onboarding_links(),
				)
				_issue_email(
					tenant=tenant,
					to_email=requested_email,
					purpose=EmailQueue.PURPOSE_INVITATION,
					subject="You have been invited to a tenant workspace",
					template_name="tenancy/emails/invitation_email.html",
					context={
						"company_name": tenant.name,
						"subdomain": payload["subdomain"],
						"invitation_url": setup_url,
						"expires_at": invitation.expires_at,
					},
					fallback_text=f"Accept your invitation by visiting {setup_url}",
					mail_route="platform",
				)

				_record_audit(
					request,
					action="tenant.invitation.resent",
					tenant=tenant,
					target_type="tenant",
					target_id=tenant.id,
					metadata={"domain": domain_name, "email": requested_email},
				)

				return Response(
					{
						"message": "Existing tenant found. Invitation re-sent.",
						"tenant_id": tenant.id,
						"domain": domain_name,
						"existing_tenant": True,
					},
					status=status.HTTP_200_OK,
				)

			domain = domain_name
			plan_slug = normalize_plan_slug(payload.get("plan") or "pro")
			plan_limits = _get_package_limits(plan_slug)
			raw_token, invitation = Invitation.issue_token(
				token_type=Invitation.TOKEN_TYPE_INVITATION,
				email=payload["admin_email"],
				invitee_full_name=payload.get("admin_full_name", ""),
				subdomain=payload["subdomain"],
				company_name=payload["company_name"],
				invited_by_email=getattr(request.user, "email", ""),
				ttl_minutes=60 * 24,
				metadata={
					"domain": domain,
					"custom_domain": payload.get("custom_domain", ""),
					"plan": plan_slug,
					"max_users": payload.get("max_users", plan_limits["max_users"]),
					"max_branches": payload.get("max_branches", plan_limits["max_branches"]),
					"max_members_per_branch": plan_limits["max_members_per_branch"],
					"max_trainers_per_branch": plan_limits["max_trainers_per_branch"],
				},
			)

			setup_url = _build_frontend_url(
				f"/accept-invite?token={quote(raw_token)}",
				subdomain=payload["subdomain"],
				domain=domain,
				prefer_public=_prefer_public_onboarding_links(),
			)
			_issue_email(
				tenant=None,
				to_email=payload["admin_email"],
				purpose=EmailQueue.PURPOSE_INVITATION,
				subject="You have been invited to a tenant workspace",
				template_name="tenancy/emails/invitation_email.html",
				context={
					"company_name": payload["company_name"],
					"subdomain": payload["subdomain"],
					"invitation_url": setup_url,
					"expires_at": invitation.expires_at,
				},
				fallback_text=f"Accept your invitation by visiting {setup_url}",
				mail_route="platform",
			)

			_record_audit(
				request,
				action="tenant.invitation.created",
				tenant=None,
				target_type="pending_tenant",
				target_id=invitation.id,
				metadata={"domain": domain, "email": payload["admin_email"]},
			)

			return Response(
				{
					"message": "Invitation created and email queued. Tenant will be created after invite acceptance.",
					"pending_invitation_id": invitation.id,
					"domain": domain,
				},
				status=status.HTTP_201_CREATED,
			)


class TenantAdminInvitationDetailView(APIView):
	permission_classes = [
		IsPlatformFeaturePermission.require("platform.tenants", "edit"),
	]

	def _get_pending_invitation(self, pk):
		with schema_context(get_public_schema_name()):
			return generics.get_object_or_404(
				Invitation,
				pk=pk,
				token_type=Invitation.TOKEN_TYPE_INVITATION,
				used_at__isnull=True,
			)

	def delete(self, request, pk):
		invitation = self._get_pending_invitation(pk)
		with schema_context(get_public_schema_name()):
			invitation.delete()
		_record_audit(
			request,
			action="tenant.invitation.revoked",
			tenant=invitation.tenant,
			target_type="pending_tenant",
			target_id=pk,
			metadata={"email": invitation.email, "subdomain": invitation.subdomain},
		)
		return Response(status=status.HTTP_204_NO_CONTENT)

	def patch(self, request, pk):
		action = request.query_params.get("action")
		if action != "resend":
			return Response({"detail": "Unsupported action."}, status=status.HTTP_400_BAD_REQUEST)

		with schema_context(get_public_schema_name()):
			invitation = generics.get_object_or_404(
				Invitation,
				pk=pk,
				token_type=Invitation.TOKEN_TYPE_INVITATION,
			)
			if invitation.used_at is not None:
				return Response(
					{"detail": "Invitation has already been accepted."},
					status=status.HTTP_400_BAD_REQUEST,
				)

			raw_token = _rotate_tenant_invitation_token(invitation)
			try:
				setup_url = _send_tenant_invitation_email(invitation, request, raw_token)
			except Exception as exc:
				return Response(
					{"error": f"Failed to send invitation email: {str(exc)}"},
					status=status.HTTP_500_INTERNAL_SERVER_ERROR,
				)

		_record_audit(
			request,
			action="tenant.invitation.resent",
			tenant=invitation.tenant,
			target_type="pending_tenant",
			target_id=invitation.id,
			metadata={"email": invitation.email, "subdomain": invitation.subdomain},
		)
		return Response(
			{
				"message": "Invitation resent successfully",
				"invitation_sent": True,
				"invite_url": setup_url,
			},
			status=status.HTTP_200_OK,
		)


class InvitationValidationAPIView(APIView):
	permission_classes = [AllowAny]

	def post(self, request):
		serializer = InvitationTokenSerializer(data=request.data)
		serializer.is_valid(raise_exception=True)

		invitation = Invitation.from_raw_token(serializer.validated_data["token"])
		if invitation is None or not invitation.is_usable:
			return Response({"detail": "Invalid or expired token."}, status=status.HTTP_400_BAD_REQUEST)
		if not _tenant_entry_is_allowed(invitation.tenant):
			return _tenant_entry_blocked_response()

		domain = _assert_token_request_scope(request, invitation)

		return Response(
			{
				"token_type": invitation.token_type,
				"email": invitation.email,
				"full_name": invitation.invitee_full_name,
				"company_name": invitation.company_name,
				"subdomain": invitation.subdomain,
				"tenant_domain": domain,
				"expires_at": invitation.expires_at,
				"password_setup_url": _build_frontend_url(
					f"/{_token_type_to_path(invitation.token_type)}?token={quote(serializer.validated_data['token'])}",
					subdomain=invitation.subdomain,
					domain=domain,
					prefer_public=_prefer_public_onboarding_links(),
				),
			}
		)


class PasswordSetupAPIView(APIView):
	permission_classes = [AllowAny]
	throttle_classes = [
		# BurstAnonRateThrottle,
		# BurstUserRateThrottle,
		# SustainedAnonRateThrottle,
		# SustainedUserRateThrottle,
		ScopedRateThrottle,
	]
	throttle_scope = "tenant_password_setup"

	def post(self, request):
		serializer = PasswordSetupSerializer(data=request.data)
		serializer.is_valid(raise_exception=True)
		payload = serializer.validated_data

		existing_invitation = Invitation.from_raw_token(payload["token"])
		if existing_invitation is None:
			return Response({"detail": "Invalid or expired token."}, status=status.HTTP_400_BAD_REQUEST)
		if not _tenant_entry_is_allowed(existing_invitation.tenant):
			return _tenant_entry_blocked_response()
		if existing_invitation.used_at is not None:
			domain = _assert_token_request_scope(request, existing_invitation)
			return _password_setup_success_response(
				existing_invitation,
				domain=domain,
				message="Password was already configured successfully.",
			)
		if existing_invitation.is_expired:
			return Response({"detail": "Invalid or expired token."}, status=status.HTTP_400_BAD_REQUEST)

		with transaction.atomic():
			invitation = Invitation.from_raw_token(payload["token"], for_update=True)
			if invitation is None:
				return Response({"detail": "Invalid or expired token."}, status=status.HTTP_400_BAD_REQUEST)
			if not _tenant_entry_is_allowed(invitation.tenant):
				return _tenant_entry_blocked_response()
			if invitation.used_at is not None:
				domain = _assert_token_request_scope(request, invitation)
				return _password_setup_success_response(
					invitation,
					domain=domain,
					message="Password was already configured successfully.",
				)
			if invitation.is_expired:
				return Response({"detail": "Invalid or expired token."}, status=status.HTTP_400_BAD_REQUEST)

			domain = _assert_token_request_scope(request, invitation)

			if invitation.token_type not in {
				Invitation.TOKEN_TYPE_VERIFICATION,
				Invitation.TOKEN_TYPE_INVITATION,
				Invitation.TOKEN_TYPE_PASSWORD_RESET,
			}:
				return Response({"detail": "Token type is not allowed for password setup."}, status=400)

			email = invitation.email.lower().strip()
			is_owner_setup = invitation.token_type in {
				Invitation.TOKEN_TYPE_VERIFICATION,
				Invitation.TOKEN_TYPE_INVITATION,
			}
			setup_time = timezone.now()

			tenant = invitation.tenant
			if tenant is None:
				if not is_owner_setup:
					return Response({"detail": "Tenant context not found."}, status=status.HTTP_400_BAD_REQUEST)

				metadata = invitation.metadata or {}
				plan_slug = normalize_plan_slug(metadata.get("plan"))
				tenant, domain = _create_tenant_with_domains(
					company_name=invitation.company_name,
					subdomain=invitation.subdomain,
					owner_email=email,
					custom_domain=metadata.get("custom_domain", ""),
					primary_domain=metadata.get("domain", ""),
					max_users=int(metadata.get("max_users", 10) or 10),
					max_branches=int(metadata.get("max_branches", 1) or 1),
					max_members_per_branch=int(metadata.get("max_members_per_branch", 0) or 0),
					max_trainers_per_branch=int(metadata.get("max_trainers_per_branch", 0) or 0),
					plan=plan_slug,
				)
				invitation.tenant = tenant
				invitation.save(update_fields=["tenant"])
				_bootstrap_tenant_branding_defaults(tenant)
			else:
				plan_slug = None  # existing tenant — no subscription payment needed
				domain = tenant.domains.filter(is_primary=True).values_list("domain", flat=True).first() or domain

			metadata = invitation.metadata or {}
			is_member_invite = is_owner_setup and bool(metadata.get("member_invite"))

			with schema_context(tenant.schema_name):
				user = User.objects.filter(email__iexact=email).first()
				if user is None:
					if not is_owner_setup:
						return Response({"detail": "User account not found."}, status=status.HTTP_400_BAD_REQUEST)
					if is_member_invite:
						user = User.objects.create_user(
							email=email,
							password=payload["password"],
							role="staff",
							full_name=invitation.invitee_full_name,
							tenant=tenant,
							is_staff=False,
							is_superuser=False,
							email_verified=True,
							password_set_at=setup_time,
						)
					else:
						user = User.objects.create_user(
							email=email,
							password=payload["password"],
							role="superuser",
							full_name=invitation.invitee_full_name,
							tenant=tenant,
							is_staff=True,
							is_superuser=True,
							email_verified=True,
							password_set_at=setup_time,
						)
				else:
					user.set_password(payload["password"])
					user.is_active = True
					if user.tenant_id is None:
						user.tenant = tenant
					user.email_verified = True
					user.password_set_at = setup_time
					if invitation.invitee_full_name and not user.full_name:
						user.full_name = invitation.invitee_full_name
					if is_owner_setup and not is_member_invite:
						user.role = "superuser"
						user.is_staff = True
						user.is_superuser = True
					user.save()

				# Assign the tenant RBAC role for member invitations.
				if is_member_invite:
					role_slug = metadata.get("role_slug", "")
					invite_branch_id = metadata.get("branch_id")
					if role_slug:
						from apps.access.models import Role, UserRole as TenantUserRole
						try:
							role_obj = Role.objects.get(slug=role_slug)
							user_role, _ = TenantUserRole.objects.get_or_create(
								user_id=user.id,
								role=role_obj,
								defaults={
									"user_email": user.email,
									"assigned_by_email": invitation.invited_by_email,
									"branch_id": invite_branch_id,
								},
							)
							if invite_branch_id and user_role.branch_id != invite_branch_id:
								user_role.branch_id = invite_branch_id
								user_role.save(update_fields=["branch"])
							invalidate_user_permissions(connection.schema_name, user.id)
						except Role.DoesNotExist:
							pass  # Role deleted since invite was sent; user can still log in

					# Apply branch assignment to TrainerProfile if present.
					if invite_branch_id:
						try:
							from apps.trainer.models import TrainerProfile
							TrainerProfile.objects.filter(user=user).update(branch_id=invite_branch_id)
						except Exception:
							pass  # Best-effort; TrainerProfile may not exist yet

			invitation.used_at = setup_time
			invitation.save(update_fields=["used_at"])

		# Fire platform-admin notification for new tenant registrations
		if plan_slug is not None:
			try:
				from apps.reminder.utils import create_notification
				create_notification(
					notification_type='tenant_registered',
					title=f'New gym registered: {tenant.name}',
					actor_name=tenant.name,
					actor_email=email,
					target_type='tenant',
					target_id=str(tenant.id),
				)
			except Exception:
				pass  # Notifications are best-effort; do not break the registration flow

		# For new owner onboarding flows, optionally initiate subscription payment
		# when the selected package requires immediate charge.
		payment_info = None
		if plan_slug and is_owner_setup and not is_member_invite:
			contact_phone = str((metadata or {}).get("contact_phone", "") or "").strip()
			payment_info = _maybe_initiate_subscription_payment(
				tenant,
				plan_slug,
				request,
				contact_phone=contact_phone,
				contact_email=email,
				contact_name=(invitation.invitee_full_name or tenant.name or "Customer"),
			)
			if payment_info and not payment_info.get('is_trial', True):
				try:
					from apps.reminder.utils import create_notification
					create_notification(
						notification_type='tenant_subscribed',
						title=f'{tenant.name} subscribed to {plan_slug}',
						actor_name=tenant.name,
						actor_email=email,
						target_type='tenant',
						target_id=str(tenant.id),
						metadata={'plan': plan_slug},
					)
				except Exception:
					pass  # Notifications are best-effort

		return _password_setup_success_response(invitation, domain=domain, payment_info=payment_info)

class TenantAuthenticationAPIView(APIView):
	permission_classes = [AllowAny]
	throttle_classes = [
		# BurstAnonRateThrottle,
		# BurstUserRateThrottle,
		# SustainedAnonRateThrottle,
		# SustainedUserRateThrottle,
		ScopedRateThrottle,
	]
	throttle_scope = "tenant_auth"

	def post(self, request):
		serializer = TenantAuthSerializer(data=request.data)
		serializer.is_valid(raise_exception=True)
		payload = serializer.validated_data

		domain_name = payload["domain"] or full_domain_for_subdomain(payload["subdomain"], request=request)
		domain = Domain.objects.filter(domain=domain_name).select_related("tenant").first()
		if domain is None:
			return Response({"detail": "Invalid tenant domain."}, status=status.HTTP_400_BAD_REQUEST)

		tenant = domain.tenant
		if not _tenant_entry_is_allowed(tenant):
			return _tenant_entry_blocked_response()

		email = payload["email"]
		cache_key = f"tenant_auth:{domain_name}:{email}"
		failed_attempts = int(cache.get(cache_key, 0))
		if failed_attempts >= 5:
			return Response({"detail": "Too many failed attempts. Try later."}, status=status.HTTP_429_TOO_MANY_REQUESTS)

		with schema_context(tenant.schema_name):
			user = User.objects.filter(email__iexact=email).first()
			if user is None or not user.check_password(payload["password"]):
				cache.set(cache_key, failed_attempts + 1, timeout=15 * 60)
				return Response({"detail": "Invalid credentials."}, status=status.HTTP_401_UNAUTHORIZED)

			if not user.is_active:
				return Response({"detail": "User account is inactive."}, status=status.HTTP_403_FORBIDDEN)

			user.last_login = timezone.now()
			if user.tenant_id is None:
				user.tenant = tenant
				user.save(update_fields=["last_login", "tenant"])
			else:
				user.save(update_fields=["last_login"])

			refresh = RefreshToken.for_user(user)
			refresh["tenant_schema"] = tenant.schema_name
			refresh["tenant_name"] = tenant.name
			refresh["tenant_domain"] = domain_name

			access = refresh.access_token
			access["tenant_schema"] = tenant.schema_name
			access["tenant_name"] = tenant.name
			access["tenant_domain"] = domain_name

		cache.delete(cache_key)

		_record_audit(
			request,
			action="tenant.auth.login",
			tenant=tenant,
			target_type="user",
			target_id=user.id,
			metadata={"email": email, "domain": domain_name},
		)

		post_login_path = getattr(settings, "TENANT_POST_LOGIN_PATH", "/AdminDashboard")
		redirect_url = _build_frontend_url(
			post_login_path,
			subdomain=payload.get("subdomain") or domain_name.split(".")[0],
			domain=domain_name,
		)

		return Response(
			{
				"access": str(access),
				"refresh": str(refresh),
				"tenant": {
					"id": tenant.id,
					"name": tenant.name,
					"schema_name": tenant.schema_name,
					"domain": domain_name,
				},
				"redirect_url": redirect_url,
			}
		)


class PasswordResetRequestAPIView(APIView):
	permission_classes = [AllowAny]
	throttle_classes = [
		# BurstAnonRateThrottle,
		# BurstUserRateThrottle,
		# SustainedAnonRateThrottle,
		# SustainedUserRateThrottle,
		ScopedRateThrottle,
	]
	throttle_scope = "tenant_password_reset"

	def post(self, request):
		serializer = PasswordResetRequestSerializer(data=request.data)
		serializer.is_valid(raise_exception=True)
		payload = serializer.validated_data

		domain_name = payload["domain"] or full_domain_for_subdomain(payload["subdomain"], request=request)
		domain = Domain.objects.filter(domain=domain_name).select_related("tenant").first()

		if domain is None:
			return Response({"message": "If the account exists, reset instructions were sent."})

		tenant = domain.tenant
		if not _tenant_entry_is_allowed(tenant):
			return Response({"message": "If the account exists, reset instructions were sent."})

		email = payload["email"]

		with schema_context(tenant.schema_name):
			user = User.objects.filter(email__iexact=email).first()

		if user is None:
			return Response({"message": "If the account exists, reset instructions were sent."})

		raw_token, invitation = Invitation.issue_token(
			token_type=Invitation.TOKEN_TYPE_PASSWORD_RESET,
			tenant=tenant,
			email=email,
			invitee_full_name=user.full_name,
			subdomain=payload.get("subdomain") or domain_name.split(".")[0],
			company_name=tenant.name,
			ttl_minutes=30,
			metadata={"domain": domain_name},
		)

		reset_url = _build_frontend_url(
			f"/reset-password?token={quote(raw_token)}",
			subdomain=payload.get("subdomain") or invitation.subdomain,
			domain=domain_name,
		)
		_issue_email(
			tenant=tenant,
			to_email=email,
			purpose=EmailQueue.PURPOSE_PASSWORD_RESET,
			subject="Reset your tenant password",
			template_name="tenancy/emails/password_reset_email.html",
			context={
				"company_name": tenant.name,
				"reset_url": reset_url,
				"expires_at": invitation.expires_at,
			},
			fallback_text=f"Reset your password using {reset_url}",
		)

		return Response({"message": "If the account exists, reset instructions were sent."})


class PasswordResetConfirmAPIView(PasswordSetupAPIView):
	"""Dedicated endpoint for password-reset token confirmation."""


class TenantAdminOverviewAPIView(APIView):
	permission_classes = [
		IsPlatformFeaturePermission.require("platform.tenants", "view"),
	]

	def get(self, request):
		def load():
			with schema_context(get_public_schema_name()):
				tenants = Tenant.objects.all()
				total = tenants.count()
				active = tenants.filter(is_enabled=True).count()
				suspended = tenants.filter(status="suspended").count()
				trial = tenants.filter(status="trial").count()
				users = _count_tenant_admin_users()
				pending_invites = Invitation.objects.filter(
					token_type=Invitation.TOKEN_TYPE_INVITATION,
					used_at__isnull=True,
				).count()
			return {
				"total_tenants": total,
				"active_tenants": active,
				"suspended_tenants": suspended,
				"trial_tenants": trial,
				"tenant_admin_accounts": users,
				"pending_invitations": pending_invites,
			}

		payload = get_cached_value(tenant_overview_key(), TENANT_OVERVIEW_TTL, load)
		return Response(payload)


class TenantAdminListAPIView(generics.ListAPIView):
	permission_classes = [
		IsPlatformFeaturePermission.require("platform.tenants", "view"),
	]
	serializer_class = TenantListSerializer

	def get_queryset(self):
		with schema_context(get_public_schema_name()):
			tenant_ids = list(Tenant.objects.order_by("name").values_list("id", flat=True))
		return Tenant.objects.filter(id__in=tenant_ids).prefetch_related("domains").order_by("name")

	def list(self, request, *args, **kwargs):
		queryset = self.filter_queryset(self.get_queryset())
		page = self.paginate_queryset(queryset)
		tenants = page if page is not None else queryset
		context = self.get_serializer_context()
		context["tenant_admins_map"] = build_tenant_admins_map(tenants)
		serializer = self.get_serializer(tenants, many=True, context=context)
		if page is not None:
			return self.get_paginated_response(serializer.data)
		return Response(serializer.data)


class TenantAdminDetailAPIView(generics.RetrieveUpdateAPIView):
	permission_classes = [
		IsPlatformFeaturePermission.require("platform.tenants", "view"),
	]

	def get_permissions(self):
		if self.request.method.lower() in {"patch", "put"}:
			return [IsPlatformFeaturePermission.require("platform.tenants", "edit")()]
		return super().get_permissions()

	def get_queryset(self):
		with schema_context(get_public_schema_name()):
			tenant_ids = list(Tenant.objects.values_list("id", flat=True))
		return Tenant.objects.filter(id__in=tenant_ids).prefetch_related("domains")

	def get_serializer_class(self):
		if self.request.method.lower() in {"patch", "put"}:
			return TenantUpdateSerializer
		return TenantListSerializer

	def perform_update(self, serializer):
		with schema_context(get_public_schema_name()):
			tenant = serializer.save()
			new_timezone = serializer.validated_data.get("timezone")
			new_locale = serializer.validated_data.get("locale")

		if new_timezone or new_locale:
			_sync_tenant_dashboard_settings(
				tenant_id=tenant.id,
				schema_name=tenant.schema_name,
				timezone_value=new_timezone,
				locale_value=new_locale,
			)

		_record_audit(
			self.request,
			action="tenant.updated",
			tenant=tenant,
			target_type="tenant",
			target_id=tenant.id,
			metadata=serializer.validated_data,
		)


class TenantAdminActivationAPIView(APIView):
	permission_classes = [
		IsPlatformFeaturePermission.require("platform.tenants", "edit"),
	]

	def post(self, request, tenant_id):
		serializer = TenantStatusSerializer(data=request.data)
		serializer.is_valid(raise_exception=True)

		with schema_context(get_public_schema_name()):
			tenant = Tenant.objects.filter(id=tenant_id).first()
			if tenant is None:
				return Response({"detail": "Tenant not found."}, status=status.HTTP_404_NOT_FOUND)

			tenant.is_enabled = serializer.validated_data["is_enabled"]
			if not tenant.is_enabled:
				tenant.status = "suspended"
			elif tenant.status == "suspended":
				tenant.status = "active"
			tenant.save(update_fields=["is_enabled", "status", "updated_at"])

		_record_audit(
			request,
			action="tenant.activation.changed",
			tenant=tenant,
			target_type="tenant",
			target_id=tenant.id,
			metadata={"is_enabled": tenant.is_enabled, "status": tenant.status},
		)

		return Response({"message": "Tenant status updated.", "is_enabled": tenant.is_enabled, "status": tenant.status})


class TenantAuditLogListAPIView(generics.ListAPIView):
	permission_classes = [
		IsPlatformFeaturePermission.require("platform.audit_logs", "view"),
	]

	def get(self, request):
		with schema_context(get_public_schema_name()):
			logs = list(TenantAuditLog.objects.select_related("tenant").order_by("-created_at")[:200])
		payload = [
			{
				"id": item.id,
				"tenant": item.tenant.name if item.tenant else "",
				"action": item.action,
				"actor_email": item.actor_email,
				"target_type": item.target_type,
				"target_id": item.target_id,
				"ip_address": item.ip_address,
				"created_at": item.created_at,
				"metadata": item.metadata,
			}
			for item in logs
		]
		return Response(payload)


class TenantMemberInviteAPIView(APIView):
	"""Invite a staff member into the current tenant workspace.

	Only accessible from a tenant schema by a user with role-admin privileges.
	Creates an Invitation token, stores the target role slug in metadata, and
	sends a password-setup email.  When the invitee clicks the link and sets
	their password (via PasswordSetupAPIView), the UserRole is automatically
	assigned.
	"""

	permission_classes = [IsAuthenticated]

	def _assert_role_admin(self, user):
		from apps.access.permissions import IsRoleAdmin
		return (
			user.is_superuser
			or user.is_staff
			or getattr(user, "role", "") == "admin"
			or IsRoleAdmin().has_permission(type("_R", (), {"user": user})(), None)
		)

	def post(self, request):
		if _is_public_schema_request(request):
			return Response(
				{"detail": "Member invitations are only available inside a tenant workspace."},
				status=status.HTTP_403_FORBIDDEN,
			)

		from apps.access.models import UserRole
		has_branch_manager_role = UserRole.objects.filter(
			user_id=request.user.id,
			role__slug="branch_manager",
		).exists()

		if not self._assert_role_admin(request.user) and not has_branch_manager_role:
			return Response({"detail": "You do not have permission to invite members."}, status=status.HTTP_403_FORBIDDEN)

		email = (request.data.get("email") or "").strip().lower()
		full_name = (request.data.get("full_name") or "").strip()
		role_slug = (request.data.get("role_slug") or "").strip()
		branch_id = request.data.get("branch_id") or request.data.get("branch") or None

		if not email:
			return Response({"detail": "email is required."}, status=status.HTTP_400_BAD_REQUEST)
		if not role_slug:
			return Response({"detail": "role_slug is required."}, status=status.HTTP_400_BAD_REQUEST)

		# Validate the role exists in this tenant schema.
		from apps.access.models import Role
		try:
			role_obj = Role.objects.get(slug=role_slug)
		except Role.DoesNotExist:
			return Response(
				{"detail": f"Role '{role_slug}' does not exist in this workspace."},
				status=status.HTTP_400_BAD_REQUEST,
			)

		# Branch managers can only invite users to branches they manage.
		is_tenant_admin = bool(
			request.user.is_superuser
			or request.user.is_staff
			or getattr(request.user, "role", "") == "admin"
		)
		if not is_tenant_admin:
			from apps.gym_branch.models import Branch
			if has_branch_manager_role:
				managed_branch_ids = list(
					Branch.objects.filter(manager_id=request.user.id).values_list("id", flat=True)
				)
				if not managed_branch_ids:
					return Response(
						{"detail": "No managed branch is configured for this account."},
						status=status.HTTP_403_FORBIDDEN,
					)

				if branch_id is None:
					branch_id = managed_branch_ids[0]
				else:
					try:
						branch_id_int = int(branch_id)
					except (TypeError, ValueError):
						return Response(
							{"detail": "Invalid branch selection."},
							status=status.HTTP_400_BAD_REQUEST,
						)
					if branch_id_int not in managed_branch_ids:
						return Response(
							{"detail": "You can only invite users to your managed branch."},
							status=status.HTTP_403_FORBIDDEN,
						)
					branch_id = branch_id_int

		# Get the tenant from the current request.
		tenant = getattr(request, "tenant", None)
		if tenant is None:
			return Response({"detail": "Tenant context not found."}, status=status.HTTP_400_BAD_REQUEST)

		# Resolve the primary domain for this tenant (from the public schema).
		with schema_context(get_public_schema_name()):
			primary_domain = (
				tenant.domains.filter(is_primary=True).values_list("domain", flat=True).first()
				or full_domain_for_subdomain(tenant.schema_name.replace("_", "-"), request=request)
			)

		subdomain = tenant.schema_name.replace("_", "-")
		company_name = tenant.name

		# Revoke any open (unused, non-expired) invitation for this email in this tenant.
		with schema_context(get_public_schema_name()):
			Invitation.objects.filter(
				email__iexact=email,
				tenant=tenant,
				token_type=Invitation.TOKEN_TYPE_INVITATION,
				used_at__isnull=True,
			).update(expires_at=timezone.now())

			raw_token, invitation = Invitation.issue_token(
				token_type=Invitation.TOKEN_TYPE_INVITATION,
				tenant=tenant,
				email=email,
				invitee_full_name=full_name,
				subdomain=subdomain,
				company_name=company_name,
				invited_by_email=getattr(request.user, "email", ""),
				ttl_minutes=60 * 48,  # 48 hours
				metadata={
					"member_invite": True,
					"role_slug": role_slug,
					"role_name": role_obj.name,
					"domain": primary_domain,
					**({"branch_id": int(branch_id)} if branch_id else {}),
				},
			)

		setup_url = _build_frontend_url(
			f"/accept-invite?token={quote(raw_token)}",
			subdomain=subdomain,
			domain=primary_domain,
			prefer_public=False,
		)

		_issue_email(
			tenant=tenant,
			to_email=email,
			purpose=EmailQueue.PURPOSE_INVITATION,
			subject=f"You've been invited to {company_name} on Fithive",
			template_name="tenancy/emails/member_invitation_email.html",
			context={
				"company_name": company_name,
				"invitee_full_name": full_name,
				"invited_by": getattr(request.user, "email", ""),
				"role_name": role_obj.name,
				"invitation_url": setup_url,
				"expires_at": invitation.expires_at,
			},
			fallback_text=f"You have been invited to {company_name}. Set your password: {setup_url}",
		)

		_record_audit(
			request,
			action="tenant.member.invited",
			tenant=tenant,
			target_type="invitation",
			target_id=invitation.id,
			metadata={"email": email, "role_slug": role_slug, "domain": primary_domain},
		)

		return Response(
			{"message": f"Invitation sent to {email}.", "email": email, "role": role_slug},
			status=status.HTTP_201_CREATED,
		)


# ─────────────────────────────────────────────────────────────────────────────
# Change Password — available in both tenant and public schemas
# Any authenticated user may change their own password.
# ─────────────────────────────────────────────────────────────────────────────

class ChangePasswordView(APIView):
	"""Allow any authenticated user (tenant or platform admin) to change their password.

	POST /api/v1/tenancy/password/change/
	Body: { current_password, new_password }
	"""

	permission_classes = [IsAuthenticated]

	def post(self, request):
		current_password = (request.data.get("current_password") or "").strip()
		new_password = (request.data.get("new_password") or "").strip()

		if not current_password or not new_password:
			return Response(
				{"detail": "current_password and new_password are required."},
				status=status.HTTP_400_BAD_REQUEST,
			)

		if not request.user.check_password(current_password):
			return Response(
				{"detail": "Current password is incorrect."},
				status=status.HTTP_400_BAD_REQUEST,
			)

		if len(new_password) < 8:
			return Response(
				{"detail": "New password must be at least 8 characters."},
				status=status.HTTP_400_BAD_REQUEST,
			)

		request.user.set_password(new_password)
		request.user.password_set_at = timezone.now()
		request.user.save(update_fields=["password", "password_set_at"])
		return Response({"detail": "Password changed successfully."})


class PlatformSettingsAPIView(APIView):
	"""Singleton platform-wide settings (public schema only).

	GET  /tenants/admin/platform-settings/ — requires platform.settings:view
	PATCH /tenants/admin/platform-settings/ — requires platform.settings:edit
	"""

	def get_permissions(self):
		if self.request.method.upper() in {"PATCH", "PUT"}:
			return [IsPlatformFeaturePermission.require("platform.settings", "edit")()]
		return [IsPlatformFeaturePermission.require("platform.settings", "view")()]

	def _obj(self):
		with schema_context(get_public_schema_name()):
			obj, _ = PlatformSettings.objects.get_or_create(pk=1)
			return obj

	def get(self, request):
		obj = self._obj()
		return Response(PlatformSettingsSerializer(obj).data)

	def patch(self, request):
		obj = self._obj()
		previous_default_language = obj.default_language
		serializer = PlatformSettingsSerializer(obj, data=request.data, partial=True)
		serializer.is_valid(raise_exception=True)
		with schema_context(get_public_schema_name()):
			serializer.save()

		new_default_language = serializer.instance.default_language
		if (
			"default_language" in serializer.validated_data
			and previous_default_language != new_default_language
		):
			_propagate_platform_default_language(
				old_language=previous_default_language,
				new_language=new_default_language,
			)

		return Response(serializer.data)
