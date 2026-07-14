from unittest.mock import patch
from datetime import timedelta

from django.core import mail
from django.test import override_settings
from django.utils import timezone
from django_tenants.utils import schema_context
from rest_framework import status
from rest_framework.test import APITestCase, APIRequestFactory

from apps.dashboard.models import GymPreferences, GymProfile
from apps.identity.models import User
from .models import (
	Domain,
	EmailQueue,
	Feature,
	Invitation,
	PaymentGateway,
	PlatformPackage,
	PlatformPackageFeature,
	PlatformSettings,
	Tenant,
	TenantFeatureFlag,
)
from .services import sync_tenant_features
from .views import PasswordSetupAPIView


class TenancyModelTests(APITestCase):
	def setUp(self):
		with schema_context("public"):
			self.tenant = Tenant.objects.create(
				schema_name="tenant_model_test",
				name="Model Tenant",
				slug="model-tenant",
				code="MODELTEST",
				owner_email="owner@model.test",
				billing_email="owner@model.test",
				status="active",
				is_trial=False,
			)

	def test_domain_is_normalized_to_lowercase(self):
		domain = Domain.objects.create(domain="TenantA.Example.COM", tenant=self.tenant, is_primary=True)
		self.assertEqual(domain.domain, "tenanta.example.com")

	def test_invitation_issue_and_lookup(self):
		raw_token, invitation = Invitation.issue_token(
			token_type=Invitation.TOKEN_TYPE_VERIFICATION,
			tenant=self.tenant,
			email="admin@model.test",
			subdomain="modeltenant",
			company_name="Model Tenant",
			ttl_minutes=30,
		)
		found = Invitation.from_raw_token(raw_token)
		self.assertIsNotNone(found)
		self.assertEqual(found.id, invitation.id)
		self.assertTrue(found.expires_at > timezone.now())

	def test_sync_tenant_features_maps_legacy_pro_plan_to_starter_package(self):
		with schema_context("public"):
			feature = Feature.objects.create(
				key="cms.banners",
				name="Banners",
				sort_order=10,
				is_system=True,
			)
			package = PlatformPackage.objects.create(
				slug="starter",
				name="Starter",
				description="Starter",
				price_monthly="29.00",
				price_yearly="290.00",
				max_users=25,
				max_branches=1,
				trial_days=0,
				is_active=True,
				is_public=True,
				highlight=True,
				sort_order=2,
			)
			PlatformPackageFeature.objects.create(
				package=package,
				feature=feature,
				is_enabled=True,
			)
			self.tenant.plan = "pro"
			self.tenant.save(update_fields=["plan", "updated_at"])

			summary = sync_tenant_features(self.tenant)
			flag = TenantFeatureFlag.objects.get(tenant=self.tenant, feature=feature)

		self.assertGreaterEqual(summary["added"] + summary["kept"], 1)
		self.assertTrue(flag.is_enabled)
		self.assertEqual(flag.source, TenantFeatureFlag.SOURCE_PACKAGE)


@override_settings(
	EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
	PUBLIC_FRONTEND_URL="http://localhost:5173",
	TENANT_FRONTEND_BASE_DOMAIN="localhost",
	TENANT_FRONTEND_SCHEME="http",
	TENANT_FRONTEND_PORT="5173",
	PUBLIC_DOMAIN="testserver",
)
class TenancyApiTests(APITestCase):
	def setUp(self):
		with schema_context("public"):
			self.public = Tenant.objects.create(
				schema_name="public",
				name="Public",
				slug="public",
				code="PUBLICTEST",
				owner_email="root@test.local",
				billing_email="root@test.local",
				status="active",
				is_trial=False,
			)
			Domain.objects.get_or_create(domain="testserver", tenant=self.public, defaults={"is_primary": True})
			self.public_user = User.objects.create_superuser(
				email="root@test.local",
				password="Test@1234",
				tenant=self.public,
			)

			self.tenant = Tenant.objects.create(
				schema_name="tenant_api_test",
				name="API Tenant",
				slug="api-tenant",
				code="APITENANT",
				owner_email="admin@api.test",
				billing_email="admin@api.test",
				status="active",
				is_trial=False,
			)
			Domain.objects.create(domain="api.testserver", tenant=self.tenant, is_primary=True)

		with schema_context(self.tenant.schema_name):
			self.user = User.objects.create_superuser(
				email="admin@api.test",
				password="Test@1234",
				tenant=self.tenant,
			)

	def test_registration_rejects_duplicate_subdomain(self):
		payload = {
			"subdomain": "api",
			"company_name": "Duplicate Co",
			"admin_email": "owner@duplicate.test",
		}
		res = self.client.post(
			"/api/v1/tenancy/register/",
			payload,
			format="json",
			HTTP_HOST="testserver",
		)
		self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
		self.assertIn("subdomain", res.data)

	def test_tenant_auth_login_with_domain(self):
		payload = {
			"email": "admin@api.test",
			"password": "Test@1234",
			"domain": "api.testserver",
		}
		res = self.client.post(
			"/api/v1/tenancy/auth/login/",
			payload,
			format="json",
			HTTP_HOST="testserver",
		)
		self.assertEqual(res.status_code, status.HTTP_200_OK)
		self.assertIn("access", res.data)
		self.assertIn("refresh", res.data)
		self.assertEqual(res.data["tenant"]["schema_name"], self.tenant.schema_name)

	def test_platform_tenant_locale_patch_syncs_tenant_preferences_language(self):
		self.client.force_authenticate(user=self.public_user)

		res = self.client.patch(
			f"/api/v1/tenancy/admin/tenants/{self.tenant.id}/",
			{"locale": "bn"},
			format="json",
			HTTP_HOST="testserver",
		)
		self.assertEqual(res.status_code, status.HTTP_200_OK)

		with schema_context("public"):
			self.tenant.refresh_from_db()
			self.assertEqual(self.tenant.locale, "bn")

		with schema_context(self.tenant.schema_name):
			prefs, _ = GymPreferences.objects.get_or_create(pk=1)
			self.assertEqual(prefs.language, "bn")

	def test_platform_default_language_patch_updates_tenants_still_on_previous_default(self):
		with schema_context("public"):
			PlatformSettings.objects.update_or_create(
				pk=1,
				defaults={"default_timezone": "Asia/Dhaka", "default_language": "en"},
			)
			self.tenant.locale = "en"
			self.tenant.save(update_fields=["locale", "updated_at"])

		with schema_context(self.tenant.schema_name):
			GymPreferences.objects.update_or_create(
				pk=1,
				defaults={"language": "en"},
			)

		self.client.force_authenticate(user=self.public_user)
		res = self.client.patch(
			"/api/v1/tenancy/admin/platform-settings/",
			{"default_language": "hi"},
			format="json",
			HTTP_HOST="testserver",
		)
		self.assertEqual(res.status_code, status.HTTP_200_OK)

		with schema_context("public"):
			self.tenant.refresh_from_db()
			self.assertEqual(self.tenant.locale, "hi")

		with schema_context(self.tenant.schema_name):
			prefs = GymPreferences.objects.get(pk=1)
			self.assertEqual(prefs.language, "hi")

	def test_superadmin_invite_requires_authentication(self):
		payload = {
			"subdomain": "newtenant",
			"company_name": "New Tenant",
			"admin_email": "admin@newtenant.test",
		}
		res = self.client.post(
			"/api/v1/tenancy/admin/invitations/",
			payload,
			format="json",
			HTTP_HOST="testserver",
		)
		self.assertIn(res.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

	def test_superadmin_invite_defers_tenant_creation_from_tenant_schema_request(self):
		self.client.force_authenticate(user=self.public_user)
		payload = {
			"subdomain": "managed",
			"company_name": "Managed Tenant",
			"admin_email": "admin@managed.test",
		}

		res = self.client.post(
			"/api/v1/tenancy/admin/invitations/",
			payload,
			format="json",
			HTTP_HOST="testserver",
		)

		self.assertEqual(res.status_code, status.HTTP_201_CREATED)
		with schema_context("public"):
			self.assertFalse(Tenant.objects.filter(schema_name="managed").exists())
			self.assertFalse(Domain.objects.filter(domain="managed.api.testserver").exists())
			self.assertTrue(
				Invitation.objects.filter(
					tenant__isnull=True,
					subdomain="managed",
					email="admin@managed.test",
					used_at__isnull=True,
				).exists()
			)

		email_log = EmailQueue.objects.get(to_email="admin@managed.test", purpose=EmailQueue.PURPOSE_INVITATION)
		self.assertEqual(email_log.status, EmailQueue.STATUS_SENT)
		self.assertTrue(email_log.context["invitation_url"].startswith("http://managed.localhost:5173/accept-invite?token="))
		self.assertIn("http://managed.localhost:5173/accept-invite?token=", email_log.text_body)
		self.assertIn("http://managed.localhost:5173/accept-invite?token=", mail.outbox[-1].body)

	def test_list_tenant_invitations_returns_pending_only(self):
		self.client.force_authenticate(user=self.public_user)
		with schema_context("public"):
			Invitation.objects.create(
				token_type=Invitation.TOKEN_TYPE_PLATFORM_INVITE,
				email="platform@example.com",
				subdomain="platform",
				company_name="Platform",
				token_hash="platform-invite-hash",
				expires_at=timezone.now() + timedelta(days=1),
			)
			tenant_invite = Invitation.objects.create(
				token_type=Invitation.TOKEN_TYPE_INVITATION,
				email="tenant-pending@example.com",
				subdomain="pendingco",
				company_name="Pending Co",
				token_hash="tenant-pending-hash",
				expires_at=timezone.now() + timedelta(days=1),
			)

		res = self.client.get(
			"/api/v1/tenancy/admin/invitations/",
			HTTP_HOST="testserver",
		)
		self.assertEqual(res.status_code, status.HTTP_200_OK)
		emails = [row["email"] for row in res.data]
		self.assertIn("tenant-pending@example.com", emails)
		self.assertNotIn("platform@example.com", emails)

	def test_revoke_tenant_invitation(self):
		self.client.force_authenticate(user=self.public_user)
		with schema_context("public"):
			invitation = Invitation.objects.create(
				token_type=Invitation.TOKEN_TYPE_INVITATION,
				email="revoke@example.com",
				subdomain="revokeco",
				company_name="Revoke Co",
				token_hash="revoke-hash",
				expires_at=timezone.now() + timedelta(days=1),
			)
			invitation_id = invitation.id

		res = self.client.delete(
			f"/api/v1/tenancy/admin/invitations/{invitation_id}/",
			HTTP_HOST="testserver",
		)
		self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)
		with schema_context("public"):
			self.assertFalse(Invitation.objects.filter(pk=invitation_id).exists())

	def test_resend_tenant_invitation(self):
		self.client.force_authenticate(user=self.public_user)
		with schema_context("public"):
			invitation = Invitation.objects.create(
				token_type=Invitation.TOKEN_TYPE_INVITATION,
				email="resend@example.com",
				subdomain="resendco",
				company_name="Resend Co",
				token_hash="resend-old-hash",
				expires_at=timezone.now() + timedelta(days=1),
				metadata={"domain": "resendco.api.testserver"},
			)
			invitation_id = invitation.id
			old_hash = invitation.token_hash

		res = self.client.patch(
			f"/api/v1/tenancy/admin/invitations/{invitation_id}/?action=resend",
			HTTP_HOST="testserver",
		)
		self.assertEqual(res.status_code, status.HTTP_200_OK)
		self.assertTrue(res.data["invitation_sent"])
		with schema_context("public"):
			invitation.refresh_from_db()
			self.assertNotEqual(invitation.token_hash, old_hash)

	def test_tenant_overview_pending_invitations_scoped_to_tenant_type(self):
		self.client.force_authenticate(user=self.public_user)
		with schema_context("public"):
			before = Invitation.objects.filter(
				token_type=Invitation.TOKEN_TYPE_INVITATION,
				used_at__isnull=True,
			).count()
			Invitation.objects.create(
				token_type=Invitation.TOKEN_TYPE_PLATFORM_INVITE,
				email="platform-only@example.com",
				subdomain="plat",
				company_name="Plat",
				token_hash="platform-only-hash",
				expires_at=timezone.now() + timedelta(days=1),
			)
			Invitation.objects.create(
				token_type=Invitation.TOKEN_TYPE_INVITATION,
				email="tenant-only@example.com",
				subdomain="tenantonly",
				company_name="Tenant Only",
				token_hash="tenant-only-hash",
				expires_at=timezone.now() + timedelta(days=1),
			)
			after = Invitation.objects.filter(
				token_type=Invitation.TOKEN_TYPE_INVITATION,
				used_at__isnull=True,
			).count()

		res = self.client.get(
			"/api/v1/tenancy/admin/overview/",
			HTTP_HOST="testserver",
		)
		self.assertEqual(res.status_code, status.HTTP_200_OK)
		self.assertEqual(res.data["pending_invitations"], after)
		self.assertEqual(after, before + 1)

	def test_tenant_schema_superuser_cannot_use_tenant_management(self):
		self.client.force_authenticate(user=self.user)

		res = self.client.get(
			"/api/v1/tenancy/admin/overview/",
			format="json",
			HTTP_HOST="api.testserver",
		)

		self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

	def test_identity_login_rejects_suspended_tenant(self):
		with schema_context("public"):
			self.tenant.status = "suspended"
			self.tenant.is_enabled = False
			self.tenant.save(update_fields=["status", "is_enabled", "updated_at"])

		res = self.client.post(
			"/api/v1/identity/login/",
			{"email": "admin@api.test", "password": "Test@1234"},
			format="json",
			HTTP_HOST="api.testserver",
		)

		self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)
		self.assertEqual(str(res.data["detail"]), "Tenant workspace is suspended.")

	def test_identity_login_allows_trial_tenant(self):
		with schema_context("public"):
			self.tenant.status = "trial"
			self.tenant.is_enabled = True
			self.tenant.save(update_fields=["status", "is_enabled", "updated_at"])

		res = self.client.post(
			"/api/v1/identity/login/",
			{"email": "admin@api.test", "password": "Test@1234"},
			format="json",
			HTTP_HOST="api.testserver",
		)

		self.assertEqual(res.status_code, status.HTTP_200_OK)
		self.assertIn("access", res.data)
		self.assertIn("refresh", res.data)

	def test_tenant_auth_login_rejects_suspended_tenant(self):
		with schema_context("public"):
			self.tenant.status = "suspended"
			self.tenant.is_enabled = False
			self.tenant.save(update_fields=["status", "is_enabled", "updated_at"])

		res = self.client.post(
			"/api/v1/tenancy/auth/login/",
			{
				"email": "admin@api.test",
				"password": "Test@1234",
				"domain": "api.testserver",
			},
			format="json",
			HTTP_HOST="testserver",
		)

		self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
		self.assertEqual(res.data["detail"], "Tenant workspace is suspended.")

	def test_token_validation_rejects_suspended_tenant(self):
		with schema_context("public"):
			self.tenant.status = "suspended"
			self.tenant.is_enabled = False
			self.tenant.save(update_fields=["status", "is_enabled", "updated_at"])

		raw_token, _ = Invitation.issue_token(
			token_type=Invitation.TOKEN_TYPE_PASSWORD_RESET,
			tenant=self.tenant,
			email="admin@api.test",
			subdomain="api",
			company_name=self.tenant.name,
			ttl_minutes=30,
			metadata={"domain": "api.testserver"},
		)

		res = self.client.post(
			"/api/v1/tenancy/tokens/validate/",
			{"token": raw_token},
			format="json",
			HTTP_HOST="api.testserver",
		)

		self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
		self.assertEqual(res.data["detail"], "Tenant workspace is suspended.")

	def test_password_reset_request_is_blocked_for_suspended_tenant(self):
		with schema_context("public"):
			self.tenant.status = "suspended"
			self.tenant.is_enabled = False
			self.tenant.save(update_fields=["status", "is_enabled", "updated_at"])

		starting_invitation_count = Invitation.objects.filter(
			tenant=self.tenant,
			token_type=Invitation.TOKEN_TYPE_PASSWORD_RESET,
		).count()
		starting_email_count = EmailQueue.objects.filter(
			tenant=self.tenant,
			purpose=EmailQueue.PURPOSE_PASSWORD_RESET,
		).count()

		res = self.client.post(
			"/api/v1/tenancy/password/reset/request/",
			{"email": "admin@api.test", "domain": "api.testserver"},
			format="json",
			HTTP_HOST="testserver",
		)

		self.assertEqual(res.status_code, status.HTTP_200_OK)
		self.assertEqual(res.data["message"], "If the account exists, reset instructions were sent.")
		self.assertEqual(
			Invitation.objects.filter(tenant=self.tenant, token_type=Invitation.TOKEN_TYPE_PASSWORD_RESET).count(),
			starting_invitation_count,
		)
		self.assertEqual(
			EmailQueue.objects.filter(tenant=self.tenant, purpose=EmailQueue.PURPOSE_PASSWORD_RESET).count(),
			starting_email_count,
		)

	def test_password_reset_confirm_rejects_suspended_tenant(self):
		with schema_context("public"):
			self.tenant.status = "suspended"
			self.tenant.is_enabled = False
			self.tenant.save(update_fields=["status", "is_enabled", "updated_at"])

		raw_token, _ = Invitation.issue_token(
			token_type=Invitation.TOKEN_TYPE_PASSWORD_RESET,
			tenant=self.tenant,
			email="admin@api.test",
			subdomain="api",
			company_name=self.tenant.name,
			ttl_minutes=30,
			metadata={"domain": "api.testserver"},
		)

		res = self.client.post(
			"/api/v1/tenancy/password/reset/confirm/",
			{
				"token": raw_token,
				"password": "Updated@1234",
				"confirm_password": "Updated@1234",
			},
			format="json",
			HTTP_HOST="api.testserver",
		)

		self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
		self.assertEqual(res.data["detail"], "Tenant workspace is suspended.")

	def test_tenant_activation_can_be_updated_from_tenant_schema_request(self):
		self.client.force_authenticate(user=self.public_user)

		res = self.client.post(
			f"/api/v1/tenancy/admin/tenants/{self.tenant.id}/activation/",
			{"is_enabled": False},
			format="json",
			HTTP_HOST="testserver",
		)

		self.assertEqual(res.status_code, status.HTTP_200_OK)
		with schema_context("public"):
			self.tenant.refresh_from_db()
			self.assertFalse(self.tenant.is_enabled)
			self.assertEqual(self.tenant.status, "suspended")

	def test_registration_email_uses_tenant_specific_frontend_url(self):
		payload = {
			"subdomain": "freshgym",
			"company_name": "Fresh Gym",
			"admin_email": "owner@freshgym.test",
		}

		res = self.client.post(
			"/api/v1/tenancy/register/",
			payload,
			format="json",
			HTTP_HOST="testserver",
		)

		self.assertEqual(res.status_code, status.HTTP_201_CREATED)
		email_log = EmailQueue.objects.get(to_email="owner@freshgym.test", purpose=EmailQueue.PURPOSE_VERIFICATION)
		self.assertEqual(email_log.status, EmailQueue.STATUS_SENT)
		self.assertTrue(email_log.context["verification_url"].startswith("http://freshgym.localhost:5173/SetTenantPassword?token="))
		self.assertIn("http://freshgym.localhost:5173/SetTenantPassword?token=", email_log.text_body)
		self.assertIn("http://freshgym.localhost:5173/SetTenantPassword?token=", mail.outbox[-1].body)

	def test_registration_email_uses_https_tenant_subdomain_in_production_mode(self):
		payload = {
			"subdomain": "prodgym",
			"company_name": "Prod Gym",
			"admin_email": "owner@prodgym.test",
		}

		with self.settings(
			PUBLIC_FRONTEND_URL="https://fitssort.com",
			TENANT_FRONTEND_BASE_DOMAIN="fitssort.com",
			TENANT_FRONTEND_SCHEME="https",
			TENANT_FRONTEND_PORT="",
		):
			res = self.client.post(
				"/api/v1/tenancy/register/",
				payload,
				format="json",
				HTTP_HOST="testserver",
			)

		self.assertEqual(res.status_code, status.HTTP_201_CREATED)
		email_log = EmailQueue.objects.get(to_email="owner@prodgym.test", purpose=EmailQueue.PURPOSE_VERIFICATION)
		self.assertTrue(email_log.context["verification_url"].startswith("https://prodgym.fitssort.com/SetTenantPassword?token="))

	def test_invitation_email_uses_https_tenant_subdomain_in_production_mode(self):
		self.client.force_authenticate(user=self.public_user)
		payload = {
			"subdomain": "prodinvite",
			"company_name": "Prod Invite Gym",
			"admin_email": "admin@prodinvite.test",
		}

		with self.settings(
			PUBLIC_FRONTEND_URL="https://fitssort.com",
			TENANT_FRONTEND_BASE_DOMAIN="fitssort.com",
			TENANT_FRONTEND_SCHEME="https",
			TENANT_FRONTEND_PORT="",
		):
			res = self.client.post(
				"/api/v1/tenancy/admin/invitations/",
				payload,
				format="json",
				HTTP_HOST="testserver",
			)

		self.assertEqual(res.status_code, status.HTTP_201_CREATED)
		email_log = EmailQueue.objects.get(to_email="admin@prodinvite.test", purpose=EmailQueue.PURPOSE_INVITATION)
		self.assertTrue(email_log.context["invitation_url"].startswith("https://prodinvite.fitssort.com/accept-invite?token="))

	def test_token_validation_rejects_wrong_tenant_host(self):
		raw_token, _ = Invitation.issue_token(
			token_type=Invitation.TOKEN_TYPE_INVITATION,
			tenant=self.tenant,
			email="admin@api.test",
			subdomain="api",
			company_name=self.tenant.name,
			ttl_minutes=30,
			metadata={"domain": "api.testserver"},
		)

		res = self.client.post(
			"/api/v1/tenancy/tokens/validate/",
			{"token": raw_token},
			format="json",
			HTTP_HOST="other.testserver",
		)

		self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
		self.assertEqual(res.data["detail"], "Token does not belong to this tenant domain.")

	def test_token_validation_allows_www_public_host(self):
		with override_settings(PUBLIC_DOMAIN="fitssort.com"):
			raw_token, _ = Invitation.issue_token(
				token_type=Invitation.TOKEN_TYPE_INVITATION,
				tenant=self.tenant,
				email="admin@api.test",
				subdomain="api",
				company_name=self.tenant.name,
				ttl_minutes=30,
				metadata={"domain": "api.testserver"},
			)

			res = self.client.post(
				"/api/v1/tenancy/tokens/validate/",
				{"token": raw_token},
				format="json",
				HTTP_HOST="www.fitssort.com",
			)

		self.assertEqual(res.status_code, status.HTTP_200_OK)

	def test_token_validation_returns_tenant_specific_password_url(self):
		raw_token, _ = Invitation.issue_token(
			token_type=Invitation.TOKEN_TYPE_VERIFICATION,
			email="verify@api.test",
			subdomain="verifygym",
			company_name="Verify Gym",
			ttl_minutes=30,
			metadata={"domain": "verifygym.testserver"},
		)

		res = self.client.post(
			"/api/v1/tenancy/tokens/validate/",
			{"token": raw_token},
			format="json",
			HTTP_HOST="testserver",
		)

		self.assertEqual(res.status_code, status.HTTP_200_OK)
		self.assertEqual(res.data["tenant_domain"], "verifygym.testserver")
		self.assertTrue(res.data["password_setup_url"].startswith("http://verifygym.localhost:5173/SetTenantPassword?token="))

	def test_password_setup_returns_tenant_specific_login_url(self):
		raw_token, _ = Invitation.issue_token(
			token_type=Invitation.TOKEN_TYPE_VERIFICATION,
			email="owner@login.test",
			subdomain="logingym",
			company_name="Login Gym",
			ttl_minutes=30,
			metadata={"domain": "logingym.testserver"},
		)

		res = self.client.post(
			"/api/v1/tenancy/password/setup/",
			{
				"token": raw_token,
				"password": "Test@1234",
				"confirm_password": "Test@1234",
			},
			format="json",
			HTTP_HOST="testserver",
		)

		self.assertEqual(res.status_code, status.HTTP_200_OK)
		self.assertEqual(res.data["tenant_domain"], "logingym.testserver")
		self.assertEqual(res.data["login_url"], "http://logingym.localhost:5173/Login")

		with schema_context("public"):
			tenant = Tenant.objects.get(schema_name="logingym")

		with schema_context(tenant.schema_name):
			profile = GymProfile.objects.get(pk=1)
			self.assertEqual(profile.gym_name, "Login Gym")

	def test_password_setup_retry_returns_success_for_already_used_token(self):
		factory = APIRequestFactory()
		view = PasswordSetupAPIView.as_view()
		raw_token, _ = Invitation.issue_token(
			token_type=Invitation.TOKEN_TYPE_VERIFICATION,
			email="owner@retry.test",
			subdomain="retrygym",
			company_name="Retry Gym",
			ttl_minutes=30,
			metadata={"domain": "retrygym.testserver"},
		)

		first_request = factory.post(
			"/api/v1/tenancy/password/setup/",
			{
				"token": raw_token,
				"password": "Test@1234",
				"confirm_password": "Test@1234",
			},
			format="json",
			HTTP_HOST="testserver",
		)
		second_request = factory.post(
			"/api/v1/tenancy/password/setup/",
			{
				"token": raw_token,
				"password": "Test@1234",
				"confirm_password": "Test@1234",
			},
			format="json",
			HTTP_HOST="testserver",
		)
		first_res = view(first_request)
		second_res = view(second_request)

		self.assertEqual(first_res.status_code, status.HTTP_200_OK)
		self.assertEqual(second_res.status_code, status.HTTP_200_OK)
		self.assertEqual(second_res.data["message"], "Password was already configured successfully.")
		self.assertEqual(second_res.data["tenant_domain"], "retrygym.testserver")
		self.assertEqual(second_res.data["login_url"], "http://retrygym.localhost:5173/Login")

	@patch("apps.billing.services.get_gateway")
	def test_password_setup_platform_invitation_growth_returns_payment_redirect(self, mock_get_gateway):
		class _FakeGateway:
			def initiate(self, transaction):
				return {
					"gateway_url": "https://sandbox.sslcommerz.com/EasyCheckout/test-session",
					"raw": {"status": "SUCCESS"},
				}

		mock_get_gateway.return_value = _FakeGateway()

		with schema_context("public"):
			PlatformPackage.objects.create(
				slug="growth",
				name="Growth",
				description="Growth",
				price_monthly="3490.00",
				price_yearly="33504.00",
				max_users=300,
				max_branches=3,
				trial_days=0,
				is_active=True,
				is_public=True,
				highlight=True,
				sort_order=2,
			)
			PaymentGateway.objects.create(
				slug="sslcommerz",
				name="SSLCommerz",
				is_enabled_for_tenants=True,
				platform_credentials={"store_id": "demo", "store_password": "demo"},
				is_sandbox=True,
				is_default_for_subscriptions=True,
			)

		raw_token, _ = Invitation.issue_token(
			token_type=Invitation.TOKEN_TYPE_INVITATION,
			email="owner@growth.test",
			subdomain="growthgym",
			company_name="Growth Gym",
			ttl_minutes=30,
			metadata={
				"domain": "growthgym.testserver",
				"plan": "growth",
				"max_users": 300,
				"max_branches": 3,
			},
		)

		res = self.client.post(
			"/api/v1/tenancy/password/setup/",
			{
				"token": raw_token,
				"password": "Test@1234",
				"confirm_password": "Test@1234",
			},
			format="json",
			HTTP_HOST="testserver",
		)

		self.assertEqual(res.status_code, status.HTTP_200_OK)
		self.assertTrue(res.data.get("payment_required"))
		self.assertTrue((res.data.get("payment_url") or "").startswith("https://sandbox.sslcommerz.com/"))
		self.assertFalse(res.data.get("is_trial"))
		self.assertEqual(res.data.get("trial_days"), 0)
