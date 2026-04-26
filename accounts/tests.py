from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import User


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
