from datetime import date, datetime, time, timedelta
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
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.identity.models import User
from .models import Tenant, Domain, Invitation, EmailQueue, TenantAuditLog
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
	full_domain_for_subdomain,
)


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


def _issue_email(*, tenant, to_email, purpose, subject, template_name, context, fallback_text):
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

	from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@gym.local")
	email = EmailMultiAlternatives(
		subject=subject,
		body=fallback_text,
		from_email=from_email,
		to=[to_email],
	)
	email.attach_alternative(html_body, "text/html")

	try:
		email.send(fail_silently=False)
		mail_log.status = EmailQueue.STATUS_SENT
		mail_log.sent_at = timezone.now()
		mail_log.attempts += 1
		mail_log.save(update_fields=["status", "sent_at", "attempts"])
	except Exception as exc:
		mail_log.status = EmailQueue.STATUS_FAILED
		mail_log.attempts += 1
		mail_log.last_error = str(exc)
		mail_log.save(update_fields=["status", "attempts", "last_error"])


def _derive_schema_name(subdomain):
	return subdomain.replace("-", "_")


def _request_host(request):
	if request is None:
		return ""
	return request.get_host().split(":")[0].strip().lower()


def _public_request_hosts():
	return {
		host
		for host in {
			getattr(settings, "PUBLIC_DOMAIN", "").strip().lower(),
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


def _create_tenant_with_domains(*, company_name, subdomain, owner_email, custom_domain="", primary_domain="", max_users=10,
								max_branches=1, plan="free"):
	public_schema = get_public_schema_name()
	with schema_context(public_schema):
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
			plan=(plan or "free"),
			status="trial",
			is_trial=True,
			trial_ends_at=timezone.now() + timedelta(days=14),
			max_users=max_users,
			max_branches=max_branches,
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


def _password_setup_success_response(invitation, *, domain, message="Password configured successfully."):
	tenant = invitation.tenant
	return Response(
		{
			"message": message,
			"tenant_schema": tenant.schema_name if tenant else "",
			"tenant_domain": domain,
			"login_url": _build_login_url(subdomain=invitation.subdomain, domain=domain),
		}
	)


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
	throttle_classes = [ScopedRateThrottle]
	throttle_scope = "tenant_registration"

	def post(self, request):
		serializer = TenantSelfRegistrationSerializer(data=request.data, context={"request": request})
		serializer.is_valid(raise_exception=True)
		payload = serializer.validated_data

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
					"plan": payload.get("plan", "trial") or "trial",
					"max_users": 10,
					"max_branches": 1,
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


class SuperadminInvitationAPIView(APIView):
	permission_classes = [
		IsPlatformFeaturePermission.require("platform.tenants", "edit"),
	]
	throttle_classes = [ScopedRateThrottle]
	throttle_scope = "superadmin_invitation"

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
					"plan": payload.get("plan", "pro") or "pro",
					"max_users": payload.get("max_users", 10),
					"max_branches": payload.get("max_branches", 1),
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
	throttle_classes = [ScopedRateThrottle]
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
				tenant, domain = _create_tenant_with_domains(
					company_name=invitation.company_name,
					subdomain=invitation.subdomain,
					owner_email=email,
					custom_domain=metadata.get("custom_domain", ""),
					primary_domain=metadata.get("domain", ""),
					max_users=int(metadata.get("max_users", 10) or 10),
					max_branches=int(metadata.get("max_branches", 1) or 1),
					plan=metadata.get("plan", "trial") or "trial",
				)
				invitation.tenant = tenant
				invitation.save(update_fields=["tenant"])
			else:
				domain = tenant.domains.filter(is_primary=True).values_list("domain", flat=True).first() or domain

			with schema_context(tenant.schema_name):
				user = User.objects.filter(email__iexact=email).first()
				if user is None:
					if not is_owner_setup:
						return Response({"detail": "User account not found."}, status=status.HTTP_400_BAD_REQUEST)
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
					if is_owner_setup:
						user.role = "superuser"
						user.is_staff = True
						user.is_superuser = True
					user.save()

			invitation.used_at = setup_time
			invitation.save(update_fields=["used_at"])

		return _password_setup_success_response(invitation, domain=domain)


class TenantAuthenticationAPIView(APIView):
	permission_classes = [AllowAny]
	throttle_classes = [ScopedRateThrottle]
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
	throttle_classes = [ScopedRateThrottle]
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
		with schema_context(get_public_schema_name()):
			tenants = Tenant.objects.all()
			total = tenants.count()
			active = tenants.filter(is_enabled=True).count()
			suspended = tenants.filter(status="suspended").count()
			trial = tenants.filter(status="trial").count()
			users = _count_tenant_admin_users()
			pending_invites = Invitation.objects.filter(used_at__isnull=True, expires_at__gt=timezone.now()).count()

		return Response(
			{
				"total_tenants": total,
				"active_tenants": active,
				"suspended_tenants": suspended,
				"trial_tenants": trial,
				"tenant_admin_accounts": users,
				"pending_invitations": pending_invites,
			}
		)


class TenantAdminListAPIView(generics.ListAPIView):
	permission_classes = [
		IsPlatformFeaturePermission.require("platform.tenants", "view"),
	]
	serializer_class = TenantListSerializer

	def get_queryset(self):
		with schema_context(get_public_schema_name()):
			tenant_ids = list(Tenant.objects.order_by("name").values_list("id", flat=True))
		return Tenant.objects.filter(id__in=tenant_ids).prefetch_related("domains").order_by("name")


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
