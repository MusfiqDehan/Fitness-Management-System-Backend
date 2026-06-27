from unittest.mock import MagicMock, patch
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from django_tenants.utils import schema_context
from rest_framework import status
from rest_framework.test import APIRequestFactory, APITestCase, force_authenticate

from apps.access.models import Role, UserRole
from apps.gym_branch.models import Branch
from apps.identity.models import User
from apps.tenancy.models import Domain, Feature, PaymentGateway, Tenant, TenantFeatureFlag
from apps.billing.models import PaymentTransaction, TenantPaymentGateway
from utils.tenancy_helpers import scope_queryset_by_branch_access

from .models import GymClass, Member, MemberPackage, Payment
from .views import GymClassView, MemberView, PaymentView, PublicGymClassListAPIView, PublicMemberRegistrationAPIView


class GymClassMediaApiTests(APITestCase):
	def setUp(self):
		with schema_context('public'):
			self.public = Tenant.objects.create(
				schema_name='public',
				name='Public',
				slug='public',
				code='PUBMEM01',
				owner_email='root@membership.test',
				billing_email='root@membership.test',
				status='active',
				is_trial=False,
			)
			Domain.objects.get_or_create(
				domain='testserver',
				tenant=self.public,
				defaults={'is_primary': True},
			)

			self.tenant = Tenant.objects.create(
				schema_name='membership_media_test',
				name='Membership Media Tenant',
				slug='membership-media',
				code='MEMMEDIA1',
				owner_email='admin@membership.test',
				billing_email='admin@membership.test',
				status='active',
				is_trial=False,
			)
			Domain.objects.create(domain='api.testserver', tenant=self.tenant, is_primary=True)
			feature, _ = Feature.objects.get_or_create(
				key='classes',
				defaults={'name': 'Classes', 'description': 'Class management access'},
			)
			TenantFeatureFlag.objects.get_or_create(
				tenant=self.tenant,
				feature=feature,
				defaults={
					'is_enabled': True,
					'source': TenantFeatureFlag.SOURCE_OVERRIDE,
				},
			)

		with schema_context(self.tenant.schema_name):
			self.user = User.objects.create_superuser(
				email='admin@membership.test',
				password='StrongPass123!',
				tenant=self.tenant,
			)

		self.factory = APIRequestFactory()

	def _call_tenant_view(self, view, method, path, data=None, *, user=None, format='json', **kwargs):
		request_factory = getattr(self.factory, method.lower())
		request = request_factory(path, data=data, format=format)
		request.tenant = self.tenant
		if user is not None:
			force_authenticate(request, user=user)
		with schema_context(self.tenant.schema_name):
			return view(request, **kwargs)

	def test_gym_class_admin_create_accepts_uploaded_media_url(self):
		with schema_context(self.tenant.schema_name):
			from apps.trainer.models import TrainerProfile

			trainer_user = User.objects.create_user(
				email='ava@membership.test',
				password='StrongPass123!',
				tenant=self.tenant,
				full_name='Ava Stone',
			)
			trainer_profile = TrainerProfile.objects.create(
				user=trainer_user,
				username='ava-stone',
				title='Yoga Instructor',
			)

		response = self._call_tenant_view(
			GymClassView.as_view(),
			'post',
			reverse('membership:gymclass-list'),
			{
				'name': 'Sunrise Flow',
				'class_type': 'yoga',
				'level': 'beginner',
				'instructor': 'Ava Stone',
				'trainer_profile': trainer_profile.id,
				'duration_minutes': 45,
				'capacity': 18,
				'description': 'Mobility-first morning class',
				'image_url': '/media/uploads/classes/sunrise-flow.jpg',
			},
			user=self.user,
		)

		self.assertEqual(response.status_code, status.HTTP_201_CREATED)
		self.assertEqual(response.data['image_url'], '/media/uploads/classes/sunrise-flow.jpg')
		self.assertEqual(response.data['trainer_profile'], trainer_profile.id)

	def test_gym_class_admin_create_requires_trainer(self):
		response = self._call_tenant_view(
			GymClassView.as_view(),
			'post',
			reverse('membership:gymclass-list'),
			{
				'name': 'No Trainer Class',
				'class_type': 'yoga',
				'level': 'beginner',
				'instructor': 'Nobody',
			},
			user=self.user,
		)
		self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

	def test_public_gym_classes_include_image_url(self):
		with schema_context(self.tenant.schema_name):
			GymClass.objects.create(
				name='Power Ride',
				class_type='cardio',
				level='intermediate',
				instructor='Kai Miles',
				duration_minutes=50,
				capacity=24,
				description='High-energy endurance ride.',
				image_url='/media/uploads/classes/power-ride.jpg',
				is_active=True,
			)

		response = self._call_tenant_view(
			PublicGymClassListAPIView.as_view(),
			'get',
			reverse('membership:public-gymclass-list'),
		)

		self.assertEqual(response.status_code, status.HTTP_200_OK)
		self.assertEqual(len(response.data), 1)
		self.assertEqual(response.data[0]['image_url'], '/media/uploads/classes/power-ride.jpg')


class PublicMemberCheckoutFlowTests(APITestCase):
	def setUp(self):
		with schema_context('public'):
			self.public = Tenant.objects.create(
				schema_name='public',
				name='Public',
				slug='public',
				code='PUBMEM02',
				owner_email='root2@membership.test',
				billing_email='root2@membership.test',
				status='active',
				is_trial=False,
			)
			Domain.objects.get_or_create(
				domain='testserver',
				tenant=self.public,
				defaults={'is_primary': True},
			)

			self.tenant = Tenant.objects.create(
				schema_name='membership_checkout_test',
				name='Membership Checkout Tenant',
				slug='membership-checkout',
				code='MEMCHECK1',
				owner_email='admin@membership.test',
				billing_email='admin@membership.test',
				status='active',
				is_trial=False,
			)
			Domain.objects.create(domain='checkout.testserver', tenant=self.tenant, is_primary=True)

			PaymentGateway.objects.update_or_create(
				slug='sslcommerz',
				defaults={
					'name': 'SSLCOMMERZ',
					'is_enabled_for_tenants': True,
					'config_schema': [
						{'key': 'store_id', 'required': True},
						{'key': 'store_password', 'required': True},
					],
				},
			)

		with schema_context(self.tenant.schema_name):
			self.package = MemberPackage.objects.create(
				name='Starter Package',
				package_type='monthly',
				duration_in_days=30,
				price='1500.00',
				is_active=True,
				is_published=True,
			)
			TenantPaymentGateway.objects.create(
				gateway_slug='sslcommerz',
				is_active=True,
				is_sandbox=True,
				credentials={'store_id': 'demo', 'store_password': 'secret'},
			)

		self.factory = APIRequestFactory()

	def _call_public_register(self, payload):
		request = self.factory.post(
			reverse('membership:public-register'),
			data=payload,
			format='json',
		)
		request.tenant = self.tenant
		with schema_context(self.tenant.schema_name):
			return PublicMemberRegistrationAPIView.as_view()(request)

	@patch('apps.membership.views._send_member_invitation_email', return_value='https://tenant.test/register?token=abc')
	@patch('apps.membership.views.get_gateway')
	def test_public_register_with_checkout_returns_gateway_url(self, gateway_factory, _send_mail):
		svc = MagicMock()
		svc.initiate.return_value = {
			'gateway_url': 'https://sandbox.sslcommerz.com/EasyCheckOut/test',
			'raw': {'status': 'SUCCESS'},
		}
		gateway_factory.return_value = svc

		response = self._call_public_register({
			'full_name': 'Public Buyer',
			'phone_number': '01710000001',
			'email': 'buyer@example.com',
			'membership_type': 'package',
			'member_package_id': self.package.id,
			'start_checkout': True,
			'gateway_slug': 'sslcommerz',
		})

		self.assertEqual(response.status_code, status.HTTP_201_CREATED)
		self.assertIn('gateway_url', response.data)
		self.assertIn('tran_id', response.data)

		with schema_context(self.tenant.schema_name):
			self.assertEqual(Member.objects.count(), 1)
			tx = PaymentTransaction.objects.get()
			self.assertEqual(tx.status, PaymentTransaction.STATUS_PENDING)
			self.assertEqual(tx.gateway_slug, 'sslcommerz')
			self.assertEqual(tx.gateway_response.get('flow'), 'public_member_signup')

	def test_public_register_with_checkout_rejects_when_gateway_not_configured(self):
		with schema_context(self.tenant.schema_name):
			TenantPaymentGateway.objects.filter(gateway_slug='sslcommerz').delete()

		response = self._call_public_register({
			'full_name': 'No Gateway Buyer',
			'phone_number': '01710000002',
			'email': 'nogateway@example.com',
			'membership_type': 'package',
			'member_package_id': self.package.id,
			'start_checkout': True,
			'gateway_slug': 'sslcommerz',
		})

		self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
		with schema_context(self.tenant.schema_name):
			self.assertEqual(Member.objects.count(), 0)
			self.assertEqual(PaymentTransaction.objects.count(), 0)

	def test_member_create_does_not_auto_create_hardcoded_payments(self):
		with schema_context(self.tenant.schema_name):
			member = Member.objects.create(
				full_name='No Auto Payment',
				phone_number='01710000003',
				email='noauto@example.com',
				membership_type='package',
				member_package=self.package,
			)

			self.assertIsNotNone(member.id)
			self.assertEqual(Payment.objects.filter(member=member).count(), 0)


class BranchScopedListHelpersTests(APITestCase):
	def setUp(self):
		with schema_context('public'):
			self.public = Tenant.objects.create(
				schema_name='public',
				name='Public',
				slug='public',
				code='PUBMEM03',
				owner_email='root3@membership.test',
				billing_email='root3@membership.test',
				status='active',
				is_trial=False,
			)
			Domain.objects.get_or_create(
				domain='testserver',
				tenant=self.public,
				defaults={'is_primary': True},
			)

			self.tenant = Tenant.objects.create(
				schema_name='membership_scope_test',
				name='Membership Scope Tenant',
				slug='membership-scope',
				code='MEMSCOPE1',
				owner_email='admin@scope.test',
				billing_email='admin@scope.test',
				status='active',
				is_trial=False,
			)
			Domain.objects.create(domain='scope.testserver', tenant=self.tenant, is_primary=True)

		with schema_context(self.tenant.schema_name):
			self.admin = User.objects.create_superuser(
				email='admin@scope.test',
				password='StrongPass123!',
				tenant=self.tenant,
			)
			self.branch_manager = User.objects.create_user(
				email='manager@scope.test',
				password='StrongPass123!',
				tenant=self.tenant,
				full_name='Branch Manager',
			)
			self.branch_a = Branch.objects.create(name='Downtown', manager_id=self.branch_manager.id)
			self.branch_b = Branch.objects.create(name='Uptown')

			role = Role.objects.create(name='Branch Manager', slug='branch_manager')
			UserRole.objects.create(
				user_id=self.branch_manager.id,
				user_email=self.branch_manager.email,
				branch=self.branch_a,
				role=role,
			)

			package = MemberPackage.objects.create(
				name='Starter',
				package_type='monthly',
				duration_in_days=30,
				price='1200.00',
			)

			self.member_a = Member.objects.create(
				full_name='Alice Downtown',
				phone_number='01710010001',
				membership_type='package',
				member_package=package,
				branch=self.branch_a,
			)
			self.member_b = Member.objects.create(
				full_name='Bob Uptown',
				phone_number='01710010002',
				membership_type='package',
				member_package=package,
				branch=self.branch_b,
			)

			self.payment_old = Payment.objects.create(
				member=self.member_a,
				payment_type='package',
				amount='500.00',
				payment_method='cash',
				payment_status='paid',
				payment_date=timezone.now() - timedelta(days=10),
			)
			self.payment_recent = Payment.objects.create(
				member=self.member_a,
				payment_type='package',
				amount='700.00',
				payment_method='cash',
				payment_status='paid',
				payment_date=timezone.now() - timedelta(days=1),
			)

		self.factory = APIRequestFactory()

	def test_branch_manager_member_scope_returns_only_managed_branch_records(self):
		with schema_context(self.tenant.schema_name):
			queryset = scope_queryset_by_branch_access(
				Member.objects.order_by('id'),
				self.branch_manager,
				branch_field='branch_id',
			)

			self.assertEqual(list(queryset.values_list('id', flat=True)), [self.member_a.id])

	def test_admin_branch_filter_returns_only_requested_branch_records(self):
		with schema_context(self.tenant.schema_name):
			queryset = scope_queryset_by_branch_access(
				Member.objects.order_by('id'),
				self.admin,
				branch_field='branch_id',
				branch_filter_id=str(self.branch_b.id),
			)

			self.assertEqual(list(queryset.values_list('id', flat=True)), [self.member_b.id])

	@patch("apps.billing.services.payment_confirmation.dispatch_member_payment")
	def test_membership_payment_create_dispatches_notify_channels(self, mock_dispatch):
		payload = {
			"member": self.member_a.id,
			"payment_type": "package",
			"amount": "900.00",
			"payment_method": "cash",
			"payment_status": "paid",
			"notify_channels": ["email", "in_app"],
		}
		self.client.force_authenticate(user=self.admin)
		with self.captureOnCommitCallbacks(execute=True):
			response = self.client.post(
				"/api/v1/membership/payments/",
				payload,
				format="json",
				HTTP_HOST="scope.testserver",
			)

		self.assertEqual(response.status_code, status.HTTP_201_CREATED)
		mock_dispatch.assert_called_once()
		channels = mock_dispatch.call_args[0][1]
		self.assertEqual(channels, ["email", "in_app"])

	def test_membership_payment_create_auto_generates_invoice_no(self):
		payload = {
			"member": self.member_a.id,
			"payment_type": "package",
			"amount": "850.00",
			"payment_method": "cash",
			"payment_status": "paid",
		}
		self.client.force_authenticate(user=self.admin)
		response = self.client.post(
			"/api/v1/membership/payments/",
			payload,
			format="json",
			HTTP_HOST="scope.testserver",
		)

		self.assertEqual(response.status_code, status.HTTP_201_CREATED)
		self.assertEqual(response.data["invoice_no"], f"INV-{response.data['id']:06d}")

	def test_membership_payment_create_syncs_member_package(self):
		with schema_context(self.tenant.schema_name):
			new_package = MemberPackage.objects.create(
				name='Elite',
				package_type='3_month',
				duration_in_days=90,
				price='3500.00',
			)
		payload = {
			'member': self.member_a.id,
			'payment_type': 'package',
			'amount': '3500.00',
			'payment_method': 'cash',
			'payment_status': 'due',
			'member_package_id': new_package.id,
		}
		self.client.force_authenticate(user=self.admin)
		response = self.client.post(
			'/api/v1/membership/payments/',
			payload,
			format='json',
			HTTP_HOST='scope.testserver',
		)

		self.assertEqual(response.status_code, status.HTTP_201_CREATED)
		with schema_context(self.tenant.schema_name):
			self.member_a.refresh_from_db()
			self.assertEqual(self.member_a.member_package_id, new_package.id)
		self.assertEqual(response.data['member_package_id'], new_package.id)

	def test_payment_view_get_queryset_applies_date_range_filters(self):
		request = self.factory.get(
			reverse('membership:payment-list'),
			{
				'from_date': (timezone.now() - timedelta(days=2)).date().isoformat(),
				'to_date': timezone.now().date().isoformat(),
			},
		)
		force_authenticate(request, user=self.admin)

		with schema_context(self.tenant.schema_name):
			view = PaymentView()
			view.request = request
			view.args = ()
			view.kwargs = {}

			queryset = view.get_queryset()

			self.assertEqual(list(queryset.values_list('id', flat=True)), [self.payment_recent.id])


class MemberInvitationResendTests(APITestCase):
	def setUp(self):
		with schema_context('public'):
			self.public = Tenant.objects.create(
				schema_name='public',
				name='Public',
				slug='public',
				code='PUBMEM04',
				owner_email='root4@membership.test',
				billing_email='root4@membership.test',
				status='active',
				is_trial=False,
			)
			Domain.objects.get_or_create(
				domain='testserver',
				tenant=self.public,
				defaults={'is_primary': True},
			)

			self.tenant = Tenant.objects.create(
				schema_name='membership_invite_resend',
				name='Membership Invite Resend Tenant',
				slug='membership-invite-resend',
				code='MEMINV001',
				owner_email='admin@invite.test',
				billing_email='admin@invite.test',
				status='active',
				is_trial=False,
			)
			Domain.objects.create(domain='invite.testserver', tenant=self.tenant, is_primary=True)
			members_feature, _ = Feature.objects.get_or_create(
				key='members',
				defaults={'name': 'Members', 'description': 'Member management access'},
			)
			TenantFeatureFlag.objects.get_or_create(
				tenant=self.tenant,
				feature=members_feature,
				defaults={
					'is_enabled': True,
					'source': TenantFeatureFlag.SOURCE_OVERRIDE,
				},
			)

		with schema_context(self.tenant.schema_name):
			self.admin = User.objects.create_superuser(
				email='admin@invite.test',
				password='StrongPass123!',
				tenant=self.tenant,
			)
			self.pending_member = Member.objects.create(
				full_name='Pending Member',
				phone_number='01710020001',
				email='pending@example.com',
				membership_type='monthly',
				invitation_token='pending-token-abc',
				invitation_sent_at=timezone.now(),
				invitation_expires_at=timezone.now() + timedelta(days=7),
				is_active=False,
			)
			self.registered_member = Member.objects.create(
				full_name='Registered Member',
				phone_number='01710020002',
				email='registered@example.com',
				membership_type='monthly',
				is_active=True,
			)

		self.factory = APIRequestFactory()

	def _patch_member_action(self, member_id, action, user=None):
		path = reverse('membership:member-detail', kwargs={'pk': member_id})
		request = self.factory.patch(f'{path}?action={action}')
		request.tenant = self.tenant
		force_authenticate(request, user=user or self.admin)
		with schema_context(self.tenant.schema_name):
			return MemberView.as_view()(request, pk=member_id)

	@patch('apps.membership.views._send_member_invitation_email')
	def test_resend_invitation_success(self, mock_send):
		mock_send.return_value = 'https://example.com/register?token=new'

		response = self._patch_member_action(self.pending_member.id, 'resend_invitation')

		self.assertEqual(response.status_code, status.HTTP_200_OK)
		self.assertTrue(response.data['invitation_sent'])
		mock_send.assert_called_once()

	def test_resend_invitation_rejects_registered_member(self):
		response = self._patch_member_action(self.registered_member.id, 'resend_invitation')

		self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
		self.assertIn('already completed', response.data['detail'])

	@patch('apps.membership.views._send_member_invitation_email')
	def test_member_serializer_exposes_invitation_pending(self, mock_send):
		mock_send.return_value = 'https://example.com/register?token=new'
		from .serializers import MemberSerializer

		with schema_context(self.tenant.schema_name):
			pending_data = MemberSerializer(self.pending_member).data
			registered_data = MemberSerializer(self.registered_member).data

		self.assertTrue(pending_data['invitation_pending'])
		self.assertFalse(registered_data['invitation_pending'])

	def test_cancel_invitation_clears_token(self):
		response = self._patch_member_action(self.pending_member.id, 'cancel_invitation')

		self.assertEqual(response.status_code, status.HTTP_200_OK)
		self.assertFalse(response.data['invitation_pending'])

		with schema_context(self.tenant.schema_name):
			self.pending_member.refresh_from_db()
			self.assertIsNone(self.pending_member.invitation_token)
			self.assertIsNone(self.pending_member.invitation_sent_at)
			self.assertIsNone(self.pending_member.invitation_expires_at)

	def test_cancel_invitation_rejects_registered_member(self):
		response = self._patch_member_action(self.registered_member.id, 'cancel_invitation')

		self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
		self.assertIn('no pending invitation', response.data['detail'].lower())


class MemberPendingInvitationFilterTests(APITestCase):
	def setUp(self):
		with schema_context('public'):
			self.public = Tenant.objects.create(
				schema_name='public',
				name='Public',
				slug='public',
				code='PUBMEM07',
				owner_email='root7@membership.test',
				billing_email='root7@membership.test',
				status='active',
				is_trial=False,
			)
			Domain.objects.get_or_create(
				domain='testserver',
				tenant=self.public,
				defaults={'is_primary': True},
			)
			self.tenant = Tenant.objects.create(
				schema_name='membership_pending_filter',
				name='Membership Pending Filter Tenant',
				slug='membership-pending-filter',
				code='MEMPND001',
				owner_email='admin@pending.test',
				billing_email='admin@pending.test',
				status='active',
				is_trial=False,
			)
			Domain.objects.create(domain='pending.testserver', tenant=self.tenant, is_primary=True)
			members_feature, _ = Feature.objects.get_or_create(
				key='members',
				defaults={'name': 'Members', 'description': 'Member management access'},
			)
			TenantFeatureFlag.objects.get_or_create(
				tenant=self.tenant,
				feature=members_feature,
				defaults={
					'is_enabled': True,
					'source': TenantFeatureFlag.SOURCE_OVERRIDE,
				},
			)

		with schema_context(self.tenant.schema_name):
			self.admin = User.objects.create_superuser(
				email='admin@pending.test',
				password='StrongPass123!',
				tenant=self.tenant,
			)
			self.pending_member = Member.objects.create(
				full_name='Pending Member',
				phone_number='01710030001',
				email='pending-filter@example.com',
				membership_type='monthly',
				invitation_token='pending-filter-token',
				invitation_sent_at=timezone.now(),
				invitation_expires_at=timezone.now() + timedelta(days=7),
				is_active=False,
			)
			self.registered_member = Member.objects.create(
				full_name='Registered Member',
				phone_number='01710030002',
				email='registered-filter@example.com',
				membership_type='monthly',
				is_active=True,
			)

	def test_list_filter_invitation_pending_true(self):
		self.client.force_authenticate(user=self.admin)
		response = self.client.get(
			'/api/v1/membership/members/?invitation_pending=true',
			HTTP_HOST='pending.testserver',
		)

		self.assertEqual(response.status_code, status.HTTP_200_OK)
		results = response.data.get('results', response.data)
		self.assertEqual(len(results), 1)
		self.assertEqual(results[0]['id'], self.pending_member.id)

	def test_analytics_includes_pending_invitations(self):
		self.client.force_authenticate(user=self.admin)
		response = self.client.get(
			'/api/v1/membership/members/analytics/',
			HTTP_HOST='pending.testserver',
		)

		self.assertEqual(response.status_code, status.HTTP_200_OK)
		self.assertEqual(response.data['pending_invitations'], 1)


class MemberRelationshipFieldTests(APITestCase):
	def setUp(self):
		with schema_context('public'):
			self.public = Tenant.objects.create(
				schema_name='public',
				name='Public',
				slug='public',
				code='PUBMEM05',
				owner_email='root5@membership.test',
				billing_email='root5@membership.test',
				status='active',
				is_trial=False,
			)
			Domain.objects.get_or_create(
				domain='testserver',
				tenant=self.public,
				defaults={'is_primary': True},
			)

			self.tenant = Tenant.objects.create(
				schema_name='membership_relationship_test',
				name='Membership Relationship Tenant',
				slug='membership-relationship',
				code='MEMREL001',
				owner_email='admin@relationship.test',
				billing_email='admin@relationship.test',
				status='active',
				is_trial=False,
			)
			Domain.objects.create(domain='relationship.testserver', tenant=self.tenant, is_primary=True)

		with schema_context(self.tenant.schema_name):
			self.admin = User.objects.create_superuser(
				email='admin@relationship.test',
				password='StrongPass123!',
				tenant=self.tenant,
			)
			self.package = MemberPackage.objects.create(
				name='Starter',
				package_type='monthly',
				duration_in_days=30,
				price='1200.00',
			)

	def test_relationship_with_member_create_read_update_round_trip(self):
		create_payload = {
			'full_name': 'Emergency Contact Member',
			'phone_number': '01710030001',
			'email': 'emergency@example.com',
			'membership_type': 'package',
			'member_package_id': self.package.id,
			'emergency_contact_name': 'Jane Doe',
			'emergency_contact_phone': '01710030002',
			'relationship_with_member': 'Spouse',
		}
		self.client.force_authenticate(user=self.admin)
		create_response = self.client.post(
			'/api/v1/membership/members/',
			create_payload,
			format='json',
			HTTP_HOST='relationship.testserver',
		)

		self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
		self.assertEqual(create_response.data['relationship_with_member'], 'Spouse')

		member_id = create_response.data['id']
		get_response = self.client.get(
			f'/api/v1/membership/members/{member_id}/',
			HTTP_HOST='relationship.testserver',
		)
		self.assertEqual(get_response.status_code, status.HTTP_200_OK)
		self.assertEqual(get_response.data['relationship_with_member'], 'Spouse')

		patch_response = self.client.patch(
			f'/api/v1/membership/members/{member_id}/',
			{'relationship_with_member': 'Parent'},
			format='json',
			HTTP_HOST='relationship.testserver',
		)
		self.assertEqual(patch_response.status_code, status.HTTP_200_OK)
		self.assertEqual(patch_response.data['relationship_with_member'], 'Parent')

		with schema_context(self.tenant.schema_name):
			member = Member.objects.get(pk=member_id)
			self.assertEqual(member.relationship_with_member, 'Parent')


class MemberManualUpdateTests(APITestCase):
	def setUp(self):
		with schema_context('public'):
			self.public = Tenant.objects.create(
				schema_name='public',
				name='Public',
				slug='public',
				code='PUBMEM06',
				owner_email='root6@membership.test',
				billing_email='root6@membership.test',
				status='active',
				is_trial=False,
			)
			Domain.objects.get_or_create(
				domain='testserver',
				tenant=self.public,
				defaults={'is_primary': True},
			)

			self.tenant = Tenant.objects.create(
				schema_name='membership_manual_update_test',
				name='Membership Manual Update Tenant',
				slug='membership-manual-update',
				code='MEMMAN001',
				owner_email='admin@manual.test',
				billing_email='admin@manual.test',
				status='active',
				is_trial=False,
			)
			Domain.objects.create(domain='manual.testserver', tenant=self.tenant, is_primary=True)
			members_feature, _ = Feature.objects.get_or_create(
				key='members',
				defaults={'name': 'Members', 'description': 'Member management access'},
			)
			TenantFeatureFlag.objects.get_or_create(
				tenant=self.tenant,
				feature=members_feature,
				defaults={
					'is_enabled': True,
					'source': TenantFeatureFlag.SOURCE_OVERRIDE,
				},
			)

		with schema_context(self.tenant.schema_name):
			self.admin = User.objects.create_superuser(
				email='admin@manual.test',
				password='StrongPass123!',
				tenant=self.tenant,
			)
			self.package_a = MemberPackage.objects.create(
				name='Starter',
				package_type='monthly',
				duration_in_days=30,
				price='1200.00',
			)
			self.package_b = MemberPackage.objects.create(
				name='Pro',
				package_type='3_month',
				duration_in_days=90,
				price='3000.00',
			)
			today = timezone.now().date()
			self.expired_member = Member.objects.create(
				full_name='Expired Member',
				phone_number='01710040001',
				email='expired@example.com',
				membership_type='package',
				member_package=self.package_a,
				start_date=today - timedelta(days=60),
				end_date=today - timedelta(days=10),
				is_active=False,
			)
			self.active_member = Member.objects.create(
				full_name='Active Member',
				phone_number='01710040002',
				email='active@example.com',
				membership_type='package',
				member_package=self.package_a,
				start_date=today - timedelta(days=5),
				end_date=today + timedelta(days=25),
				is_active=True,
			)

		self.client.force_authenticate(user=self.admin)
		self.host = 'manual.testserver'
		self.factory = APIRequestFactory()

	def _patch_member_action(self, member_id, action):
		path = reverse('membership:member-detail', kwargs={'pk': member_id})
		request = self.factory.patch(f'{path}?action={action}')
		request.tenant = self.tenant
		force_authenticate(request, user=self.admin)
		with schema_context(self.tenant.schema_name):
			return MemberView.as_view()(request, pk=member_id)

	def test_update_expired_member_persists_is_active_true(self):
		response = self.client.patch(
			f'/api/v1/membership/members/{self.expired_member.id}/',
			{'is_active': True},
			format='json',
			HTTP_HOST=self.host,
		)

		self.assertEqual(response.status_code, status.HTTP_200_OK)
		self.assertTrue(response.data['is_active'])
		with schema_context(self.tenant.schema_name):
			member = Member.objects.get(pk=self.expired_member.id)
			self.assertTrue(member.is_active)

	def test_update_member_does_not_recalculate_end_date_when_package_changes(self):
		original_end_date = self.active_member.end_date
		response = self.client.patch(
			f'/api/v1/membership/members/{self.active_member.id}/',
			{'member_package_id': self.package_b.id},
			format='json',
			HTTP_HOST=self.host,
		)

		self.assertEqual(response.status_code, status.HTTP_200_OK)
		with schema_context(self.tenant.schema_name):
			member = Member.objects.get(pk=self.active_member.id)
			self.assertEqual(member.end_date, original_end_date)
			self.assertEqual(member.member_package_id, self.package_b.id)

	def test_update_member_persists_explicit_end_date(self):
		new_end_date = timezone.now().date() + timedelta(days=120)
		response = self.client.patch(
			f'/api/v1/membership/members/{self.active_member.id}/',
			{'end_date': new_end_date.isoformat()},
			format='json',
			HTTP_HOST=self.host,
		)

		self.assertEqual(response.status_code, status.HTTP_200_OK)
		self.assertEqual(response.data['end_date'], new_end_date.isoformat())
		with schema_context(self.tenant.schema_name):
			member = Member.objects.get(pk=self.active_member.id)
			self.assertEqual(member.end_date, new_end_date)

	def test_activate_expired_member_persists_is_active(self):
		response = self._patch_member_action(self.expired_member.id, 'activate')

		self.assertEqual(response.status_code, status.HTTP_200_OK)
		self.assertTrue(response.data['is_active'])
		with schema_context(self.tenant.schema_name):
			member = Member.objects.get(pk=self.expired_member.id)
			self.assertTrue(member.is_active)

	def test_deactivate_active_member_persists_is_active(self):
		response = self._patch_member_action(self.active_member.id, 'deactivate')

		self.assertEqual(response.status_code, status.HTTP_200_OK)
		self.assertFalse(response.data['is_active'])
		with schema_context(self.tenant.schema_name):
			member = Member.objects.get(pk=self.active_member.id)
			self.assertFalse(member.is_active)

	def test_create_member_defaults_end_date_from_package_when_omitted(self):
		start_date = timezone.now().date()
		response = self.client.post(
			'/api/v1/membership/members/',
			{
				'full_name': 'New Package Member',
				'phone_number': '01710040003',
				'email': 'newpackage@example.com',
				'membership_type': 'package',
				'member_package_id': self.package_a.id,
				'start_date': start_date.isoformat(),
			},
			format='json',
			HTTP_HOST=self.host,
		)

		self.assertEqual(response.status_code, status.HTTP_201_CREATED)
		expected_end = start_date + timedelta(days=self.package_a.duration_in_days)
		self.assertEqual(response.data['end_date'], expected_end.isoformat())
		with schema_context(self.tenant.schema_name):
			member = Member.objects.get(pk=response.data['id'])
			self.assertEqual(member.end_date, expected_end)


class MemberImportDuplicatePhoneTests(APITestCase):
	@classmethod
	def setUpTestData(cls):
		with schema_context('public'):
			cls.public = Tenant.objects.create(
				schema_name='public',
				name='Public',
				slug='public',
				code='PUBIMP01',
				owner_email='root@import.test',
				billing_email='root@import.test',
				status='active',
				is_trial=False,
			)
			Domain.objects.get_or_create(
				domain='testserver',
				tenant=cls.public,
				defaults={'is_primary': True},
			)
			cls.tenant = Tenant.objects.create(
				schema_name='member_import_test',
				name='Member Import Tenant',
				slug='member-import',
				code='MEMIMP01',
				owner_email='admin@import.test',
				billing_email='admin@import.test',
				status='active',
				is_trial=False,
			)
			Domain.objects.create(domain='import.testserver', tenant=cls.tenant, is_primary=True)

		with schema_context(cls.tenant.schema_name):
			cls.admin = User.objects.create_superuser(
				email='admin@import.test',
				password='StrongPass123!',
				tenant=cls.tenant,
			)

	def test_import_creates_separate_members_for_duplicate_phone_numbers(self):
		csv_body = (
			'email,full_name,phone_number,date_of_birth\n'
			'parent@example.com,Parent One,1711992111,2010-01-01\n'
			'child@example.com,Child Two,1711992111,2012-06-15\n'
		)
		uploaded = SimpleUploadedFile(
			'members.csv',
			csv_body.encode('utf-8'),
			content_type='text/csv',
		)
		self.client.force_authenticate(user=self.admin)
		response = self.client.post(
			'/api/v1/membership/members/import/',
			{'file': uploaded},
			format='multipart',
			HTTP_HOST='import.testserver',
		)

		self.assertEqual(response.status_code, status.HTTP_200_OK)
		self.assertEqual(response.data['total_rows'], 2)
		self.assertEqual(response.data['created_count'], 2)
		self.assertEqual(response.data['updated_count'], 0)

		with schema_context(self.tenant.schema_name):
			members = Member.objects.filter(phone_number='1711992111').order_by('id')
			self.assertEqual(members.count(), 2)
			self.assertEqual(list(members.values_list('full_name', flat=True)), ['Parent One', 'Child Two'])

	def test_import_updates_existing_member_for_same_name_phone_dob(self):
		csv_body = (
			'email,full_name,phone_number,date_of_birth\n'
			'old@example.com,Same Person,1711992111,2010-01-01\n'
		)
		uploaded = SimpleUploadedFile(
			'members.csv',
			csv_body.encode('utf-8'),
			content_type='text/csv',
		)
		self.client.force_authenticate(user=self.admin)

		first_response = self.client.post(
			'/api/v1/membership/members/import/',
			{'file': uploaded},
			format='multipart',
			HTTP_HOST='import.testserver',
		)
		self.assertEqual(first_response.status_code, status.HTTP_200_OK)
		self.assertEqual(first_response.data['created_count'], 1)

		second_csv = (
			'email,full_name,phone_number,date_of_birth\n'
			'new@example.com,Same Person,1711992111,2010-01-01\n'
		)
		second_upload = SimpleUploadedFile(
			'members.csv',
			second_csv.encode('utf-8'),
			content_type='text/csv',
		)
		second_response = self.client.post(
			'/api/v1/membership/members/import/',
			{'file': second_upload},
			format='multipart',
			HTTP_HOST='import.testserver',
		)

		self.assertEqual(second_response.status_code, status.HTTP_200_OK)
		self.assertEqual(second_response.data['created_count'], 0)
		self.assertEqual(second_response.data['updated_count'], 1)

		with schema_context(self.tenant.schema_name):
			members = Member.objects.filter(phone_number='1711992111')
			self.assertEqual(members.count(), 1)
			self.assertEqual(members.first().email, 'new@example.com')

	def test_import_restores_soft_deleted_members_as_created(self):
		with schema_context(self.tenant.schema_name):
			member = Member.objects.create(
				full_name='Restore Me',
				phone_number='1711992999',
				date_of_birth='2010-01-01',
				email='old@example.com',
			)
			member.delete()
			self.assertEqual(Member.objects.count(), 0)
			self.assertEqual(Member.all_objects.filter(is_deleted=True).count(), 1)

		csv_body = (
			'email,full_name,phone_number,date_of_birth\n'
			'new@example.com,Restore Me,1711992999,2010-01-01\n'
		)
		uploaded = SimpleUploadedFile(
			'members.csv',
			csv_body.encode('utf-8'),
			content_type='text/csv',
		)
		self.client.force_authenticate(user=self.admin)
		response = self.client.post(
			'/api/v1/membership/members/import/',
			{'file': uploaded},
			format='multipart',
			HTTP_HOST='import.testserver',
		)

		self.assertEqual(response.status_code, status.HTTP_200_OK)
		self.assertEqual(response.data['created_count'], 1)
		self.assertEqual(response.data['updated_count'], 0)

		with schema_context(self.tenant.schema_name):
			self.assertEqual(Member.objects.count(), 1)
			restored = Member.objects.get(phone_number='1711992999')
			self.assertFalse(restored.is_deleted)
			self.assertEqual(restored.email, 'new@example.com')


class MemberAnalyticsAPIViewTests(APITestCase):
	@classmethod
	def setUpTestData(cls):
		with schema_context('public'):
			cls.public = Tenant.objects.create(
				schema_name='public',
				name='Public',
				slug='public',
				code='PUBAN01',
				owner_email='root@analytics.test',
				billing_email='root@analytics.test',
				status='active',
				is_trial=False,
			)
			Domain.objects.get_or_create(
				domain='testserver',
				tenant=cls.public,
				defaults={'is_primary': True},
			)
			cls.tenant = Tenant.objects.create(
				schema_name='member_analytics_test',
				name='Member Analytics Tenant',
				slug='member-analytics',
				code='MEMAN01',
				owner_email='admin@analytics.test',
				billing_email='admin@analytics.test',
				status='active',
				is_trial=False,
			)
			Domain.objects.create(domain='analytics.testserver', tenant=cls.tenant, is_primary=True)

		with schema_context(cls.tenant.schema_name):
			cls.admin = User.objects.create_superuser(
				email='admin@analytics.test',
				password='StrongPass123!',
				tenant=cls.tenant,
			)
			cls.premium = MemberPackage.objects.create(
				name='Premium',
				package_type='monthly',
				duration_in_days=30,
				price='100.00',
			)
			cls.starter = MemberPackage.objects.create(
				name='Starter',
				package_type='monthly',
				duration_in_days=30,
				price='50.00',
			)
			today = timezone.now().date()
			Member.objects.create(
				full_name='Active Male',
				phone_number='17110000001',
				gender='male',
				member_package=cls.premium,
				is_active=True,
				start_date=today,
				end_date=today + timedelta(days=30),
			)
			Member.objects.create(
				full_name='Expired Female',
				phone_number='17110000002',
				gender='female',
				member_package=cls.starter,
				is_active=False,
				start_date=today - timedelta(days=60),
				end_date=today - timedelta(days=1),
			)

	def test_analytics_returns_dynamic_chart_fields(self):
		self.client.force_authenticate(user=self.admin)
		response = self.client.get(
			'/api/v1/membership/members/analytics/?period=monthly',
			HTTP_HOST='analytics.testserver',
		)

		self.assertEqual(response.status_code, status.HTTP_200_OK)
		self.assertEqual(response.data['total'], 2)
		self.assertEqual(response.data['active'], 1)
		self.assertEqual(response.data['expired'], 1)
		self.assertEqual(response.data['gender_dist']['male'], 1)
		self.assertEqual(response.data['gender_dist']['female'], 1)
		self.assertIn('member_trend', response.data)
		self.assertEqual(len(response.data['member_trend']), 12)
		self.assertIn('package_breakdown', response.data)
		self.assertEqual(response.data['retention_rate'], 50.0)

		breakdown = {row['label']: row for row in response.data['package_breakdown']}
		self.assertEqual(breakdown['Premium']['active'], 1)
		self.assertEqual(breakdown['Premium']['expired'], 0)
		self.assertEqual(breakdown['Starter']['expired'], 1)
