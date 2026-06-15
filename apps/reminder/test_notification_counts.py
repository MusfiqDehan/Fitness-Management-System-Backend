from unittest.mock import patch

from django.test import override_settings
from django_tenants.utils import schema_context
from rest_framework import status
from rest_framework.test import APITestCase

from apps.identity.models import User
from apps.tenancy.models import Domain, Tenant

from .models import Notification, NotificationRead
from .utils import (
    get_notification_counts,
    personal_ws_group,
    push_notification_count,
    push_notification_counts_for_admins,
)


@override_settings(PUBLIC_DOMAIN="testserver")
class NotificationCountHelperTests(APITestCase):
    def setUp(self):
        with schema_context("public"):
            self.public = Tenant.objects.create(
                schema_name="public",
                name="Public",
                slug="public",
                code="PUBLICCNT",
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
                schema_name="notif_count_tenant",
                name="Count Tenant",
                slug="count-tenant",
                code="COUNTTEN",
                owner_email="admin@count.test",
                billing_email="admin@count.test",
                status="active",
                is_trial=False,
            )
            Domain.objects.create(
                domain="count.testserver",
                tenant=self.tenant,
                is_primary=True,
            )

        with schema_context(self.tenant.schema_name):
            self.admin_user = User.objects.create_user(
                email="admin@count.test",
                password="Test@1234",
                tenant=self.tenant,
                role="admin",
                is_staff=True,
            )
            self.member_user = User.objects.create_user(
                email="member@count.test",
                password="Test@1234",
                tenant=self.tenant,
                role="student",
                is_staff=False,
            )
            self.broadcast = Notification.objects.create(
                notification_type="member_onboarded",
                title="Broadcast",
            )
            self.personal = Notification.objects.create(
                notification_type="welcome_member",
                title="Personal",
                recipient=self.member_user,
            )

    def test_admin_counts_include_broadcast_and_personal(self):
        with schema_context(self.tenant.schema_name):
            counts = get_notification_counts(self.admin_user)
        self.assertEqual(counts["total"], 1)
        self.assertEqual(counts["unread"], 1)

    def test_member_counts_include_only_personal(self):
        with schema_context(self.tenant.schema_name):
            counts = get_notification_counts(self.member_user)
        self.assertEqual(counts["total"], 1)
        self.assertEqual(counts["unread"], 1)

    def test_mark_read_decrements_unread(self):
        with schema_context(self.tenant.schema_name):
            NotificationRead.objects.create(
                notification=self.personal,
                user=self.member_user,
            )
            counts = get_notification_counts(self.member_user)
        self.assertEqual(counts["total"], 1)
        self.assertEqual(counts["unread"], 0)

    def test_count_view_uses_shared_helper(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(
            "/api/v1/reminder/notifications/count/",
            HTTP_HOST="count.testserver",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total"], 1)
        self.assertEqual(response.data["unread"], 1)


@override_settings(PUBLIC_DOMAIN="testserver")
class NotificationWsPushTests(APITestCase):
    def setUp(self):
        with schema_context("public"):
            self.public = Tenant.objects.create(
                schema_name="public",
                name="Public",
                slug="public",
                code="PUBLICWS",
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
                schema_name="notif_ws_tenant",
                name="WS Tenant",
                slug="ws-tenant",
                code="WSTENANT",
                owner_email="admin@ws.test",
                billing_email="admin@ws.test",
                status="active",
                is_trial=False,
            )
            Domain.objects.create(
                domain="ws.testserver",
                tenant=self.tenant,
                is_primary=True,
            )

        with schema_context(self.tenant.schema_name):
            self.admin_user = User.objects.create_user(
                email="admin@ws.test",
                password="Test@1234",
                tenant=self.tenant,
                role="admin",
                is_staff=True,
            )
            self.member_user = User.objects.create_user(
                email="member@ws.test",
                password="Test@1234",
                tenant=self.tenant,
                role="student",
                is_staff=False,
            )

    @patch("apps.reminder.utils.push_ws_notification_data")
    def test_push_notification_count_sends_count_updated(self, mock_push):
        with schema_context(self.tenant.schema_name):
            Notification.objects.create(
                notification_type="welcome_member",
                title="Hello",
                recipient=self.member_user,
            )
            push_notification_count(self.member_user)

        mock_push.assert_called_once()
        group_name, payload = mock_push.call_args[0]
        self.assertEqual(
            group_name,
            personal_ws_group(self.tenant.schema_name, self.member_user.pk),
        )
        self.assertEqual(payload["event"], "count_updated")
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["unread"], 1)

    @patch("apps.reminder.utils.push_ws_notification_data")
    def test_create_notification_personal_pushes_count_updated(self, mock_push):
        with schema_context(self.tenant.schema_name):
            from .utils import create_notification

            create_notification(
                notification_type="welcome_member",
                title="Welcome",
                recipient=self.member_user,
            )

        count_events = [
            call[0][1]
            for call in mock_push.call_args_list
            if call[0][1].get("event") == "count_updated"
        ]
        self.assertEqual(len(count_events), 1)
        self.assertEqual(count_events[0]["total"], 1)
        self.assertEqual(count_events[0]["unread"], 1)

    @patch("apps.reminder.utils.push_ws_notification_data")
    def test_create_notification_broadcast_pushes_admin_counts(self, mock_push):
        with schema_context(self.tenant.schema_name):
            from .utils import create_notification

            create_notification(
                notification_type="member_onboarded",
                title="New member",
            )

        admin_group = personal_ws_group(self.tenant.schema_name, self.admin_user.pk)
        admin_count_calls = [
            call
            for call in mock_push.call_args_list
            if call[0][0] == admin_group and call[0][1].get("event") == "count_updated"
        ]
        self.assertEqual(len(admin_count_calls), 1)
        self.assertEqual(admin_count_calls[0][0][1]["unread"], 1)

    @patch("apps.reminder.views.push_notification_count")
    def test_mark_read_pushes_count(self, mock_push):
        with schema_context(self.tenant.schema_name):
            notification = Notification.objects.create(
                notification_type="welcome_member",
                title="Read me",
                recipient=self.member_user,
            )

        self.client.force_authenticate(user=self.member_user)
        response = self.client.post(
            f"/api/v1/reminder/notifications/{notification.id}/?action=mark-read",
            {},
            HTTP_HOST="ws.testserver",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_push.assert_called_once_with(self.member_user)

    @patch("apps.reminder.utils.push_ws_notification_data")
    def test_push_notification_counts_for_admins_targets_each_admin(self, mock_push):
        with schema_context(self.tenant.schema_name):
            Notification.objects.create(
                notification_type="member_onboarded",
                title="Broadcast",
            )
            push_notification_counts_for_admins()

        admin_group = personal_ws_group(self.tenant.schema_name, self.admin_user.pk)
        admin_count_calls = [
            call
            for call in mock_push.call_args_list
            if call[0][0] == admin_group and call[0][1].get("event") == "count_updated"
        ]
        self.assertEqual(len(admin_count_calls), 1)
