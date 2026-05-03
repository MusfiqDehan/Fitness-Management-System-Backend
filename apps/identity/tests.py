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
