from django.core import mail
from django.test import override_settings
from django.utils import timezone
from django_tenants.utils import schema_context
from rest_framework import status
from rest_framework.test import APITestCase

from apps.identity.models import User
from .models import Tenant, Domain, Invitation, EmailQueue


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
		self.assertTrue(email_log.context["invitation_url"].startswith("http://managed.localhost:5173/AcceptTenantInvite?token="))
		self.assertIn("http://managed.localhost:5173/AcceptTenantInvite?token=", email_log.text_body)
		self.assertIn("http://managed.localhost:5173/AcceptTenantInvite?token=", mail.outbox[-1].body)

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
			PUBLIC_FRONTEND_URL="https://gym-ms.musfiqdehan.com",
			TENANT_FRONTEND_BASE_DOMAIN="musfiqdehan.com",
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
		self.assertTrue(email_log.context["verification_url"].startswith("https://prodgym.musfiqdehan.com/SetTenantPassword?token="))

	def test_invitation_email_uses_https_tenant_subdomain_in_production_mode(self):
		self.client.force_authenticate(user=self.public_user)
		payload = {
			"subdomain": "prodinvite",
			"company_name": "Prod Invite Gym",
			"admin_email": "admin@prodinvite.test",
		}

		with self.settings(
			PUBLIC_FRONTEND_URL="https://gym-ms.musfiqdehan.com",
			TENANT_FRONTEND_BASE_DOMAIN="musfiqdehan.com",
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
		self.assertTrue(email_log.context["invitation_url"].startswith("https://prodinvite.musfiqdehan.com/AcceptTenantInvite?token="))

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
