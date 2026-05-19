from django.urls import reverse
from django_tenants.utils import schema_context
from rest_framework import status
from rest_framework.test import APIRequestFactory, APITestCase, force_authenticate

from apps.identity.models import User
from apps.tenancy.models import Domain, Feature, Tenant, TenantFeatureFlag

from .models import GymClass
from .views import GymClassView, PublicGymClassListAPIView


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
