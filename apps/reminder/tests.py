from django.test import override_settings
from django_tenants.utils import schema_context
from rest_framework import status
from rest_framework.test import APITestCase

from apps.identity.models import User
from apps.tenancy.models import Domain, Tenant

from .models import Notification


@override_settings(PUBLIC_DOMAIN="testserver")
class ReminderAccessTests(APITestCase):
	def setUp(self):
		with schema_context("public"):
			self.public = Tenant.objects.create(
				schema_name="public",
				name="Public",
				slug="public",
				code="PUBLICREM",
				owner_email="root@test.local",
				billing_email="root@test.local",
				status="active",
				is_trial=False,
			)
			Domain.objects.get_or_create(
				domain="testserver",
				tenant=self.public,
				defaults={"is_primary": True},
			)
			self.tenant = Tenant.objects.create(
				schema_name="reminder_access",
				name="Reminder Tenant",
				slug="reminder-tenant",
				code="REMINDTEN",
				owner_email="admin@reminder.test",
				billing_email="admin@reminder.test",
				status="active",
				is_trial=False,
			)
			Domain.objects.create(
				domain="reminder.testserver",
				tenant=self.tenant,
				is_primary=True,
			)

		with schema_context(self.tenant.schema_name):
			self.admin_user = User.objects.create_user(
				email="admin@reminder.test",
				password="Test@1234",
				tenant=self.tenant,
				role="admin",
				is_staff=True,
			)
			self.trainer_user = User.objects.create_user(
				email="trainer@reminder.test",
				password="Test@1234",
				tenant=self.tenant,
				role="trainer",
				is_staff=False,
			)
			Notification.objects.create(
				notification_type="member_onboarded",
				title="New member joined",
				actor_name="Member Example",
				actor_email="member@example.com",
				target_type="member",
				target_id="1",
			)

	def test_tenant_admin_can_list_and_count_notifications(self):
		self.client.force_authenticate(user=self.admin_user)

		list_response = self.client.get(
			"/api/v1/reminder/notifications/",
			HTTP_HOST="reminder.testserver",
		)
		count_response = self.client.get(
			"/api/v1/reminder/notifications/count/",
			HTTP_HOST="reminder.testserver",
		)

		self.assertEqual(list_response.status_code, status.HTTP_200_OK)
		self.assertEqual(len(list_response.data), 1)
		self.assertEqual(count_response.status_code, status.HTTP_200_OK)
		self.assertEqual(count_response.data["total"], 1)
		self.assertEqual(count_response.data["unread"], 1)

	def test_trainer_cannot_access_tenant_admin_notifications(self):
		"""Trainers can reach the feed endpoint (200) but receive an empty list because
		broadcast notifications (recipient=None) are scoped to admins only."""
		self.client.force_authenticate(user=self.trainer_user)

		list_response = self.client.get(
			"/api/v1/reminder/notifications/",
			HTTP_HOST="reminder.testserver",
		)
		count_response = self.client.get(
			"/api/v1/reminder/notifications/count/",
			HTTP_HOST="reminder.testserver",
		)

		self.assertEqual(list_response.status_code, status.HTTP_200_OK)
		self.assertEqual(len(list_response.data), 0)
		self.assertEqual(count_response.status_code, status.HTTP_200_OK)
		self.assertEqual(count_response.data["total"], 0)
		self.assertEqual(count_response.data["unread"], 0)

	def test_member_can_see_own_targeted_notification(self):
		"""A member user sees only Notification objects targeted at them."""
		with schema_context(self.tenant.schema_name):
			member_user = User.objects.create_user(
				email="member@reminder.test",
				password="Test@1234",
				tenant=self.tenant,
				role="student",
				is_staff=False,
			)
			Notification.objects.create(
				notification_type="welcome_member",
				title="Welcome!",
				recipient=member_user,
			)

		self.client.force_authenticate(user=member_user)
		response = self.client.get(
			"/api/v1/reminder/notifications/",
			HTTP_HOST="reminder.testserver",
		)
		self.assertEqual(response.status_code, status.HTTP_200_OK)
		self.assertEqual(len(response.data), 1)
		self.assertEqual(response.data[0]["notification_type"], "welcome_member")

	def test_member_cannot_see_broadcast_notifications(self):
		"""Broadcast notifications (recipient=None) are invisible to non-admin users."""
		with schema_context(self.tenant.schema_name):
			member_user = User.objects.create_user(
				email="member2@reminder.test",
				password="Test@1234",
				tenant=self.tenant,
				role="student",
				is_staff=False,
			)
			# The broadcast 'member_onboarded' notification created in setUp
			# must NOT appear for this member user.

		self.client.force_authenticate(user=member_user)
		response = self.client.get(
			"/api/v1/reminder/notifications/",
			HTTP_HOST="reminder.testserver",
		)
		self.assertEqual(response.status_code, status.HTTP_200_OK)
		self.assertEqual(len(response.data), 0)

	def test_trainer_can_see_own_targeted_notification(self):
		"""A trainer user sees only Notification objects targeted at them."""
		with schema_context(self.tenant.schema_name):
			Notification.objects.create(
				notification_type="welcome_trainer",
				title="Welcome to the team!",
				recipient=self.trainer_user,
			)

		self.client.force_authenticate(user=self.trainer_user)
		response = self.client.get(
			"/api/v1/reminder/notifications/",
			HTTP_HOST="reminder.testserver",
		)
		self.assertEqual(response.status_code, status.HTTP_200_OK)
		self.assertEqual(len(response.data), 1)
		self.assertEqual(response.data[0]["notification_type"], "welcome_trainer")
