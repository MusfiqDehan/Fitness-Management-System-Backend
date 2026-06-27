from datetime import time, timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from django_tenants.utils import schema_context

from apps.identity.models import User
from apps.membership.models import Member
from apps.membership.services.class_catalog import ClassCatalogService
from apps.membership.services.class_enrollment import ClassEnrollmentService
from apps.membership.services.class_enrollment_notification import (
    dispatch_class_enrollment_notifications,
)
from apps.tenancy.models import Domain, Tenant
from apps.trainer.models import TrainerProfile


class ClassEnrollmentNotificationTests(TestCase):
    def setUp(self):
        with schema_context('public'):
            self.public = Tenant.objects.create(
                schema_name='public',
                name='Public',
                slug='public',
                code='PUBNT01',
                owner_email='root@notify.test',
                billing_email='root@notify.test',
                status='active',
                is_trial=False,
            )
            Domain.objects.get_or_create(
                domain='testserver',
                tenant=self.public,
                defaults={'is_primary': True},
            )
            self.tenant = Tenant.objects.create(
                schema_name='class_notify_test',
                name='Class Notify Tenant',
                slug='class-notify',
                code='CLNT01',
                owner_email='admin@notify.test',
                billing_email='admin@notify.test',
                status='active',
                is_trial=False,
            )
            Domain.objects.create(domain='notify.testserver', tenant=self.tenant, is_primary=True)

        with schema_context(self.tenant.schema_name):
            self.admin = User.objects.create_superuser(
                email='admin@notify.test',
                password='StrongPass123!',
                tenant=self.tenant,
            )
            trainer_user = User.objects.create_user(
                email='trainer@notify.test',
                password='StrongPass123!',
                tenant=self.tenant,
                full_name='Coach Lee',
            )
            self.trainer = TrainerProfile.objects.create(user=trainer_user, username='coach-notify')
            member_user = User.objects.create_user(
                email='member@notify.test',
                password='StrongPass123!',
                tenant=self.tenant,
                full_name='Sam Member',
            )
            self.member = Member.objects.create(
                user=member_user,
                full_name='Sam Member',
                email='member@notify.test',
                phone_number='01700000011',
                is_active=True,
            )
            catalog = ClassCatalogService(user=self.admin)
            self.gym_class = catalog.create_gym_class_from_admin({
                'name': 'Evening Pilates',
                'class_type': 'pilates',
                'level': 'beginner',
                'trainer_profile': self.trainer,
                'duration_minutes': 45,
                'capacity': 10,
            })
            tomorrow = timezone.now().date() + timedelta(days=1)
            catalog.create_gym_schedule_from_admin({
                'title': 'Evening Pilates',
                'gym_class': self.gym_class,
                'trainer_profile': self.trainer,
                'recurrence_mode': 'one_off',
                'scheduled_date': tomorrow,
                'day_of_week': 'monday',
                'start_time': time(18, 0),
                'end_time': time(19, 0),
                'capacity': 10,
            })

        self.service = ClassEnrollmentService(user=self.admin)

    @patch('apps.membership.services.class_enrollment_notification.create_notification')
    @patch('apps.membership.services.class_enrollment_notification.EmailMultiAlternatives')
    def test_dispatch_email_and_in_app(self, mock_email_cls, mock_notify):
        with schema_context(self.tenant.schema_name):
            dispatch_class_enrollment_notifications(
                self.gym_class,
                [self.member],
                ['email', 'in_app'],
                actor=self.admin,
                tenant=self.tenant,
            )

        mock_email_cls.assert_called_once()
        email_instance = mock_email_cls.return_value
        email_instance.send.assert_called_once_with(fail_silently=True)
        self.assertIn('Evening Pilates', email_instance.attach_alternative.call_args[0][0])
        mock_notify.assert_called_once()
        self.assertEqual(mock_notify.call_args.kwargs['recipient'].email, 'member@notify.test')

    @patch(
        'apps.membership.services.class_enrollment_notification.dispatch_class_enrollment_notifications'
    )
    def test_enroll_members_passes_notify_channels_on_commit(self, mock_dispatch):
        with schema_context(self.tenant.schema_name):
            self.service.enroll_members(
                self.gym_class,
                [self.member.id],
                notify_channels=['email'],
                tenant=self.tenant,
            )

        mock_dispatch.assert_called_once()
        self.assertEqual(mock_dispatch.call_args.args[1][0].id, self.member.id)
        self.assertEqual(mock_dispatch.call_args.args[2], ['email'])

    @patch('apps.membership.services.class_enrollment_notification.EmailMultiAlternatives')
    def test_dispatch_skips_email_without_address(self, mock_email_cls):
        with schema_context(self.tenant.schema_name):
            self.member.email = ''
            self.member.save(update_fields=['email'])
            dispatch_class_enrollment_notifications(
                self.gym_class,
                [self.member],
                ['email'],
                tenant=self.tenant,
            )

        mock_email_cls.assert_not_called()
