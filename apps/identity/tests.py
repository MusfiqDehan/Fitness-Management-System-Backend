from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import User, InstructorProfile, StudentProfile


class EmailOrPhoneJWTLoginTests(APITestCase):
	def setUp(self):
		self.url = reverse("token_obtain_pair")

		self.email_user = User.objects.create_user(
			email="admin@example.com",
			password="StrongPass123!",
			role="admin",
		)

		self.phone_user = User.objects.create_user(
			phone="01700000000",
			password="StrongPass123!",
			role="staff",
		)

		self.inactive_user = User.objects.create_user(
			email="inactive@example.com",
			password="StrongPass123!",
			role="admin",
			is_active=False,
		)

	def test_login_with_email_succeeds(self):
		response = self.client.post(
			self.url,
			{"email": "admin@example.com", "password": "StrongPass123!"},
			format="json",
		)

		self.assertEqual(response.status_code, status.HTTP_200_OK)
		self.assertIn("access", response.data)
		self.assertIn("refresh", response.data)

	def test_login_with_phone_in_email_field_succeeds(self):
		response = self.client.post(
			self.url,
			{"email": "01700000000", "password": "StrongPass123!"},
			format="json",
		)

		self.assertEqual(response.status_code, status.HTTP_200_OK)
		self.assertIn("access", response.data)
		self.assertIn("refresh", response.data)

	def test_login_with_phone_field_succeeds(self):
		response = self.client.post(
			self.url,
			{"phone": "01700000000", "password": "StrongPass123!"},
			format="json",
		)

		self.assertEqual(response.status_code, status.HTTP_200_OK)
		self.assertIn("access", response.data)
		self.assertIn("refresh", response.data)

	def test_login_with_identifier_field_succeeds(self):
		response = self.client.post(
			self.url,
			{"identifier": "admin@example.com", "password": "StrongPass123!"},
			format="json",
		)

		self.assertEqual(response.status_code, status.HTTP_200_OK)
		self.assertIn("access", response.data)
		self.assertIn("refresh", response.data)

	def test_login_with_wrong_password_fails(self):
		response = self.client.post(
			self.url,
			{"email": "admin@example.com", "password": "WrongPass123!"},
			format="json",
		)

		self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

	def test_login_with_missing_identifier_fails(self):
		response = self.client.post(
			self.url,
			{"password": "StrongPass123!"},
			format="json",
		)

		self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

	def test_login_with_inactive_user_fails(self):
		response = self.client.post(
			self.url,
			{"email": "inactive@example.com", "password": "StrongPass123!"},
			format="json",
		)

		self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class identityAPIViewTests(APITestCase):
	def setUp(self):
		self.current_user_url = reverse("identity:current-user")
		self.instructor_list_url = reverse("identity:instructor-list")

		self.student_user = User.objects.create_user(
			email="student@example.com",
			password="StrongPass123!",
			role="student",
		)
		StudentProfile.objects.create(user=self.student_user, full_name="Student User")

		self.instructor_user = User.objects.create_user(
			email="instructor@example.com",
			password="StrongPass123!",
			role="instructor",
		)
		InstructorProfile.objects.create(user=self.instructor_user, full_name="Instructor User")

		self.phone_instructor = User.objects.create_user(
			phone="01700000001",
			password="StrongPass123!",
			role="instructor",
		)

	def test_current_user_get_returns_profile_aware_payload(self):
		self.client.force_authenticate(user=self.student_user)

		response = self.client.get(self.current_user_url)

		self.assertEqual(response.status_code, status.HTTP_200_OK)
		self.assertEqual(response.data["email"], "student@example.com")
		self.assertEqual(response.data["full_name"], "Student User")
		self.assertEqual(response.data["permissions"], [])

	def test_current_user_patch_validates_and_updates_email(self):
		self.client.force_authenticate(user=self.student_user)

		response = self.client.patch(
			self.current_user_url,
			{"email": "student-updated@example.com"},
			format="json",
		)

		self.assertEqual(response.status_code, status.HTTP_200_OK)
		self.student_user.refresh_from_db()
		self.assertEqual(self.student_user.email, "student-updated@example.com")

	def test_current_user_patch_rejects_empty_identity(self):
		self.client.force_authenticate(user=self.student_user)

		response = self.client.patch(
			self.current_user_url,
			{"email": "", "phone": ""},
			format="json",
		)

		self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

	def test_instructor_list_requires_auth_and_returns_name_shape(self):
		unauthenticated_response = self.client.get(self.instructor_list_url)
		self.assertEqual(unauthenticated_response.status_code, status.HTTP_401_UNAUTHORIZED)

		self.client.force_authenticate(user=self.student_user)
		response = self.client.get(self.instructor_list_url)

		self.assertEqual(response.status_code, status.HTTP_200_OK)
		self.assertEqual(
			response.data,
			[
				{"id": self.instructor_user.id, "name": "instructor@example.com"},
				{"id": self.phone_instructor.id, "name": "01700000001"},
			],
		)


@override_settings(ALLOWED_HOSTS=["testserver", "jwt.testserver", "localhost", "127.0.0.1"])
class JWTLogoutTests(APITestCase):
	def setUp(self):
		from apps.tenancy.models import Domain, Tenant
		from django_tenants.utils import schema_context

		with schema_context("public"):
			self.public_tenant = Tenant.objects.create(
				schema_name="public",
				name="Public",
				slug="public",
				code="PUBLICJWT",
				owner_email="root@jwt.test",
				billing_email="root@jwt.test",
				status="active",
				is_trial=False,
			)
			Domain.objects.get_or_create(
				domain="testserver",
				tenant=self.public_tenant,
				defaults={"is_primary": True},
			)
			User.objects.create_superuser(
				email="root@jwt.test",
				password="Test@1234",
				tenant=self.public_tenant,
			)

			self.tenant = Tenant.objects.create(
				schema_name="tenant_jwt_logout",
				name="JWT Tenant",
				slug="jwt-tenant",
				code="JWTTENANT",
				owner_email="admin@jwt.test",
				billing_email="admin@jwt.test",
				status="active",
				is_trial=False,
			)
			Domain.objects.create(domain="jwt.testserver", tenant=self.tenant, is_primary=True)

		with schema_context(self.tenant.schema_name):
			User.objects.create_superuser(
				email="admin@jwt.test",
				password="Test@1234",
				tenant=self.tenant,
			)

	def _platform_login(self):
		return self.client.post(
			"/api/v1/identity/login/",
			{"email": "root@jwt.test", "password": "Test@1234"},
			format="json",
			HTTP_HOST="testserver",
		)

	def _tenant_login(self):
		return self.client.post(
			"/api/v1/tenancy/auth/login/",
			{
				"email": "admin@jwt.test",
				"password": "Test@1234",
				"domain": "jwt.testserver",
			},
			format="json",
			HTTP_HOST="testserver",
		)

	def _logout(self, access: str, refresh: str, host: str = "testserver"):
		return self.client.post(
			"/api/v1/identity/logout/",
			{"refresh": refresh},
			format="json",
			HTTP_AUTHORIZATION=f"Bearer {access}",
			HTTP_HOST=host,
		)

	def test_platform_logout_blocks_access_and_refresh(self):
		login = self._platform_login()
		self.assertEqual(login.status_code, status.HTTP_200_OK)
		access = login.data["access"]
		refresh = login.data["refresh"]

		logout = self._logout(access, refresh)
		self.assertEqual(logout.status_code, status.HTTP_204_NO_CONTENT)

		me = self.client.get(
			"/api/v1/identity/me/",
			HTTP_AUTHORIZATION=f"Bearer {access}",
			HTTP_HOST="testserver",
		)
		self.assertEqual(me.status_code, status.HTTP_401_UNAUTHORIZED)

		refreshed = self.client.post(
			"/api/v1/identity/refresh/",
			{"refresh": refresh},
			format="json",
			HTTP_HOST="testserver",
		)
		self.assertEqual(refreshed.status_code, status.HTTP_401_UNAUTHORIZED)

	def test_tenant_logout_blocks_access_and_refresh(self):
		login = self._tenant_login()
		self.assertEqual(login.status_code, status.HTTP_200_OK)
		access = login.data["access"]
		refresh = login.data["refresh"]

		logout = self._logout(access, refresh, host="jwt.testserver")
		self.assertEqual(logout.status_code, status.HTTP_204_NO_CONTENT)

		me = self.client.get(
			"/api/v1/access/me/",
			HTTP_AUTHORIZATION=f"Bearer {access}",
			HTTP_HOST="jwt.testserver",
		)
		self.assertEqual(me.status_code, status.HTTP_401_UNAUTHORIZED)

		refreshed = self.client.post(
			"/api/v1/identity/refresh/",
			{"refresh": refresh},
			format="json",
			HTTP_HOST="jwt.testserver",
		)
		self.assertEqual(refreshed.status_code, status.HTTP_401_UNAUTHORIZED)

	def test_logout_requires_refresh_body(self):
		login = self._platform_login()
		access = login.data["access"]
		res = self.client.post(
			"/api/v1/identity/logout/",
			{},
			format="json",
			HTTP_AUTHORIZATION=f"Bearer {access}",
			HTTP_HOST="testserver",
		)
		self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

	def test_logout_requires_authentication(self):
		res = self.client.post(
			"/api/v1/identity/logout/",
			{"refresh": "not-a-valid-jwt"},
			format="json",
			HTTP_HOST="testserver",
		)
		self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)

	def test_double_logout_is_idempotent(self):
		login = self._platform_login()
		access = login.data["access"]
		refresh = login.data["refresh"]

		first = self._logout(access, refresh)
		second = self._logout(access, refresh)
		self.assertEqual(first.status_code, status.HTTP_204_NO_CONTENT)
		self.assertEqual(second.status_code, status.HTTP_204_NO_CONTENT)

	def test_tenant_auth_logout_alias(self):
		login = self._tenant_login()
		access = login.data["access"]
		refresh = login.data["refresh"]

		res = self.client.post(
			"/api/v1/tenancy/auth/logout/",
			{"refresh": refresh},
			format="json",
			HTTP_AUTHORIZATION=f"Bearer {access}",
			HTTP_HOST="jwt.testserver",
		)
		self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)

		me = self.client.get(
			"/api/v1/access/me/",
			HTTP_AUTHORIZATION=f"Bearer {access}",
			HTTP_HOST="jwt.testserver",
		)
		self.assertEqual(me.status_code, status.HTTP_401_UNAUTHORIZED)


@override_settings(ALLOWED_HOSTS=["testserver", "jwt.testserver", "localhost", "127.0.0.1"])
class PasswordChangeSessionInvalidationTests(APITestCase):
	def setUp(self):
		from apps.tenancy.models import Domain, Tenant
		from django_tenants.utils import schema_context

		with schema_context("public"):
			self.public_tenant = Tenant.objects.create(
				schema_name="public",
				name="Public",
				slug="public",
				code="PUBLICPWD",
				owner_email="root@pwd.test",
				billing_email="root@pwd.test",
				status="active",
				is_trial=False,
			)
			Domain.objects.get_or_create(
				domain="testserver",
				tenant=self.public_tenant,
				defaults={"is_primary": True},
			)
			self.user = User.objects.create_superuser(
				email="root@pwd.test",
				password="Test@1234",
				tenant=self.public_tenant,
			)

	def _login(self, password: str = "Test@1234"):
		return self.client.post(
			"/api/v1/identity/login/",
			{"email": "root@pwd.test", "password": password},
			format="json",
			HTTP_HOST="testserver",
		)

	def test_password_change_invalidates_access_and_refresh_tokens(self):
		login = self._login()
		self.assertEqual(login.status_code, status.HTTP_200_OK)
		access = login.data["access"]
		refresh = login.data["refresh"]

		change = self.client.post(
			"/api/v1/tenancy/password/change/",
			{
				"current_password": "Test@1234",
				"new_password": "NewTest@5678",
			},
			format="json",
			HTTP_AUTHORIZATION=f"Bearer {access}",
			HTTP_HOST="testserver",
		)
		self.assertEqual(change.status_code, status.HTTP_200_OK)

		self.user.refresh_from_db()
		self.assertEqual(self.user.token_version, 2)

		me = self.client.get(
			"/api/v1/identity/me/",
			HTTP_AUTHORIZATION=f"Bearer {access}",
			HTTP_HOST="testserver",
		)
		self.assertEqual(me.status_code, status.HTTP_401_UNAUTHORIZED)

		refreshed = self.client.post(
			"/api/v1/identity/refresh/",
			{"refresh": refresh},
			format="json",
			HTTP_HOST="testserver",
		)
		self.assertEqual(refreshed.status_code, status.HTTP_401_UNAUTHORIZED)

		old_password_login = self._login("Test@1234")
		self.assertEqual(old_password_login.status_code, status.HTTP_401_UNAUTHORIZED)

		new_login = self._login("NewTest@5678")
		self.assertEqual(new_login.status_code, status.HTTP_200_OK)
