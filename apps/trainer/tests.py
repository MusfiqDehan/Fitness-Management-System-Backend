from datetime import timedelta
from unittest.mock import patch

from django.urls import reverse
from django.utils import timezone
from django_tenants.utils import schema_context
from rest_framework import status
from rest_framework.test import APIRequestFactory, APITestCase, force_authenticate

from apps.identity.models import User
from apps.tenancy.models import Domain, Tenant

from .models import TrainerInvitation
from .views import TrainerInvitationView


class TrainerInvitationResendTests(APITestCase):
    def setUp(self):
        with schema_context('public'):
            self.public = Tenant.objects.create(
                schema_name='public',
                name='Public',
                slug='public',
                code='PUBTRN01',
                owner_email='root@trainer.test',
                billing_email='root@trainer.test',
                status='active',
                is_trial=False,
            )
            Domain.objects.get_or_create(
                domain='testserver',
                tenant=self.public,
                defaults={'is_primary': True},
            )

            self.tenant = Tenant.objects.create(
                schema_name='trainer_invite_resend',
                name='Trainer Invite Resend Tenant',
                slug='trainer-invite-resend',
                code='TRNINV001',
                owner_email='admin@trainer.test',
                billing_email='admin@trainer.test',
                status='active',
                is_trial=False,
            )
            Domain.objects.create(domain='trainer.testserver', tenant=self.tenant, is_primary=True)

        with schema_context(self.tenant.schema_name):
            self.admin = User.objects.create_superuser(
                email='admin@trainer.test',
                password='StrongPass123!',
                tenant=self.tenant,
            )
            self.pending_invitation = TrainerInvitation.objects.create(
                invited_email='trainer@example.com',
                invited_by=self.admin,
                token='trainer-token-abc',
                invitation_expires_at=timezone.now() + timedelta(days=7),
            )
            self.accepted_invitation = TrainerInvitation.objects.create(
                invited_email='done@example.com',
                invited_by=self.admin,
                token='trainer-token-done',
                invitation_expires_at=timezone.now() + timedelta(days=7),
                accepted_at=timezone.now(),
            )

        self.factory = APIRequestFactory()

    def _patch_invitation_action(self, invitation_id, action, user=None):
        path = reverse('trainer:trainer-invitation-detail', kwargs={'pk': invitation_id})
        request = self.factory.patch(f'{path}?action={action}')
        request.tenant = self.tenant
        force_authenticate(request, user=user or self.admin)
        with schema_context(self.tenant.schema_name):
            return TrainerInvitationView.as_view()(request, pk=invitation_id)

    @patch('apps.trainer.views._send_trainer_invitation_email')
    def test_resend_invitation_success(self, mock_send):
        mock_send.return_value = 'https://example.com/trainer/register?token=new'

        response = self._patch_invitation_action(self.pending_invitation.id, 'resend')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['invitation_sent'])
        mock_send.assert_called_once()

    def test_resend_invitation_rejects_accepted_invite(self):
        response = self._patch_invitation_action(self.accepted_invitation.id, 'resend')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('already been accepted', response.data['detail'])
