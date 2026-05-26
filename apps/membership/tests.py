from unittest.mock import MagicMock, patch

from django.urls import reverse
from django_tenants.utils import schema_context
from rest_framework import status
from rest_framework.test import APIRequestFactory, APITestCase, force_authenticate

from apps.identity.models import User
from apps.tenancy.models import Domain, Feature, PaymentGateway, Tenant, TenantFeatureFlag
from apps.billing.models import PaymentTransaction, TenantPaymentGateway

from .models import GymClass, Member, MemberPackage, Payment
from .views import GymClassView, PublicGymClassListAPIView, PublicMemberRegistrationAPIView


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
		response = self._call_tenant_view(
			GymClassView.as_view(),
			'post',
			reverse('membership:gymclass-list'),
			{
				'name': 'Sunrise Flow',
				'class_type': 'yoga',
				'level': 'beginner',
				'instructor': 'Ava Stone',
				'duration_minutes': 45,
				'capacity': 18,
				'description': 'Mobility-first morning class',
				'image_url': '/media/uploads/classes/sunrise-flow.jpg',
			},
			user=self.user,
		)

		self.assertEqual(response.status_code, status.HTTP_201_CREATED)
		self.assertEqual(response.data['image_url'], '/media/uploads/classes/sunrise-flow.jpg')

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
