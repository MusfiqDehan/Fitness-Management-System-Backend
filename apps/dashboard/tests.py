from django.urls import reverse
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework import status
from rest_framework.test import APITestCase

from apps.identity.models import User
from apps.quick_action.models import BlogCategory, Category, ClassSchedule, Contact, GymClass
from apps.membership.models import Member, MemberPackage


class DashboardAPIViewTests(APITestCase):
	def setUp(self):
		self.admin_user = User.objects.create_user(
			email='admin-dashboard@example.com',
			password='StrongPass123!',
			role='admin',
			is_staff=True,
		)
		self.member_user = User.objects.create_user(
			email='member-dashboard@example.com',
			password='StrongPass123!',
			role='student',
		)
		self.instructor_user = User.objects.create_user(
			email='coach-dashboard@example.com',
			password='StrongPass123!',
			role='instructor',
		)

	def test_dashboard_routes_resolve_for_named_endpoints(self):
		routes = [
			('dashboard:blog-list', None),
			('dashboard:blog-create', None),
			('dashboard:blog-detail', [1]),
			('dashboard:blog-update', [1]),
			('dashboard:blog-delete', [1]),
			('dashboard:blog-category-list', None),
			('dashboard:blog-category-create', None),
			('dashboard:blog-category-detail', [1]),
			('dashboard:gym-class-list', None),
			('dashboard:gym-class-levels', None),
			('dashboard:class-booking-list', None),
			('dashboard:gym-class-category-list', None),
			('dashboard:instructor-list', None),
			('dashboard:contact-list', None),
			('dashboard:contact-new-list', None),
			('dashboard:contact-mark-as-read', [1]),
			('dashboard:fithive-support-list', None),
			('dashboard:fithive-support-mark-as-read', [1]),
			('dashboard:package-list', None),
			('dashboard:gym-club-list', None),
			('dashboard:member-list', None),
			('dashboard:member-package-list', None),
			('dashboard:attendance-list', None),
			('dashboard:site-banner-list', None),
			('dashboard:promo-banner-list', None),
			('dashboard:site-settings', None),
			('dashboard:page-content-list', None),
			('dashboard:gym-schedule-list', None),
			('dashboard:file-upload', None),
		]

		for route_name, args in routes:
			url = reverse(route_name, args=args or [])
			self.assertTrue(url.startswith('/api/dashboard/'))

	def test_instructor_list_dashboard_endpoint_uses_explicit_api_view(self):
		unauthenticated_response = self.client.get(reverse('dashboard:instructor-list'))
		self.assertEqual(unauthenticated_response.status_code, status.HTTP_401_UNAUTHORIZED)

		self.client.force_authenticate(user=self.member_user)
		response = self.client.get(reverse('dashboard:instructor-list'))

		self.assertEqual(response.status_code, status.HTTP_200_OK)
		self.assertEqual(response.data, [{'id': self.instructor_user.id, 'name': 'coach-dashboard@example.com'}])

	def test_blog_category_crud_endpoints_work_with_explicit_routes(self):
		self.client.force_authenticate(user=self.admin_user)

		create_response = self.client.post(
			reverse('dashboard:blog-category-create'),
			{'name': 'Dashboard Category'},
			format='json',
		)

		self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
		category_id = create_response.data['id']

		list_response = self.client.get(reverse('dashboard:blog-category-list'))
		self.assertEqual(list_response.status_code, status.HTTP_200_OK)
		self.assertEqual(list_response.data['count'], 1)

		update_response = self.client.patch(
			reverse('dashboard:blog-category-update', args=[category_id]),
			{'name': 'Updated Dashboard Category'},
			format='json',
		)

		self.assertEqual(update_response.status_code, status.HTTP_200_OK)
		self.assertEqual(update_response.data['name'], 'Updated Dashboard Category')

		delete_response = self.client.delete(reverse('dashboard:blog-category-delete', args=[category_id]))
		self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)

	def test_gym_class_levels_and_class_booking_endpoints_preserve_behavior(self):
		category = Category.objects.create(name='Strength')
		schedule = ClassSchedule.objects.create(day='Monday', time='09:00')
		gym_class = GymClass.objects.create(
			title='Morning Strength',
			description='Strength class',
			category=category,
			class_duration='45 min',
			people=20,
			level='Beginner',
			instructor=self.instructor_user,
		)
		gym_class.class_schedule.add(schedule)

		self.client.force_authenticate(user=self.admin_user)
		levels_response = self.client.get(reverse('dashboard:gym-class-levels'))
		self.assertEqual(levels_response.status_code, status.HTTP_200_OK)
		self.assertIn('Beginner', levels_response.data)

		self.client.force_authenticate(user=self.member_user)
		booking_create_response = self.client.post(
			reverse('dashboard:class-booking-create'),
			{
				'gym_class': gym_class.id,
				'selected_schedule_id': schedule.id,
				'phone': '01700000009',
				'notes': 'Window seat',
			},
			format='json',
		)

		self.assertEqual(booking_create_response.status_code, status.HTTP_201_CREATED)
		list_response = self.client.get(reverse('dashboard:class-booking-list'))
		self.assertEqual(list_response.status_code, status.HTTP_200_OK)
		self.assertEqual(list_response.data['count'], 1)

		self.client.force_authenticate(user=self.admin_user)
		admin_list_response = self.client.get(reverse('dashboard:class-booking-list'))
		self.assertEqual(admin_list_response.status_code, status.HTTP_200_OK)
		self.assertEqual(admin_list_response.data['count'], 1)

		with CaptureQueriesContext(connection) as queries:
			budget_response = self.client.get(reverse('dashboard:class-booking-list'))

		self.assertEqual(budget_response.status_code, status.HTTP_200_OK)
		self.assertLessEqual(len(queries), 5)

	def test_contact_custom_routes_mark_and_filter_statuses(self):
		contact = Contact.objects.create(
			name='Contact User',
			email='contact@example.com',
			phone='01700000010',
			subject='Need help',
			message='Please call me back',
		)

		self.client.force_authenticate(user=self.admin_user)

		new_response = self.client.get(reverse('dashboard:contact-new-list'))
		self.assertEqual(new_response.status_code, status.HTTP_200_OK)
		self.assertEqual(len(new_response.data), 1)

		mark_read_response = self.client.patch(reverse('dashboard:contact-mark-as-read', args=[contact.id]))
		self.assertEqual(mark_read_response.status_code, status.HTTP_200_OK)

		read_response = self.client.get(reverse('dashboard:contact-read-list'))
		self.assertEqual(read_response.status_code, status.HTTP_200_OK)
		self.assertEqual(len(read_response.data), 1)

		mark_responded_response = self.client.patch(reverse('dashboard:contact-mark-as-responded', args=[contact.id]))
		self.assertEqual(mark_responded_response.status_code, status.HTTP_200_OK)

		responded_response = self.client.get(reverse('dashboard:contact-responded-list'))
		self.assertEqual(responded_response.status_code, status.HTTP_200_OK)
		self.assertEqual(len(responded_response.data), 1)

	def test_member_crud_uses_writable_member_package_field(self):
		member_package = MemberPackage.objects.create(
			name='Gold',
			package_type='monthly',
			duration_in_days=30,
			price='1500.00',
		)

		self.client.force_authenticate(user=self.admin_user)

		create_response = self.client.post(
			reverse('dashboard:member-create'),
			{
				'full_name': 'Member One',
				'phone_number': '01700000020',
				'membership_type': 'package',
				'member_package_id': member_package.id,
				'start_date': '2026-04-28',
				'is_active': True,
			},
			format='json',
		)

		self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
		member_id = create_response.data['id']
		self.assertEqual(create_response.data['member_package']['id'], member_package.id)

		list_response = self.client.get(reverse('dashboard:member-list'))
		self.assertEqual(list_response.status_code, status.HTTP_200_OK)
		self.assertEqual(list_response.data['count'], 1)

		update_response = self.client.patch(
			reverse('dashboard:member-update', args=[member_id]),
			{'membership_type': 'monthly'},
			format='json',
		)

		self.assertEqual(update_response.status_code, status.HTTP_200_OK)
		member = Member.objects.get(pk=member_id)
		self.assertIsNone(member.member_package)

	def test_site_settings_upsert_endpoint_still_works(self):
		self.client.force_authenticate(user=self.admin_user)

		first_response = self.client.post(
			reverse('dashboard:site-settings'),
			{'company_name': 'Fit Hive'},
			format='json',
		)
		self.assertEqual(first_response.status_code, status.HTTP_200_OK)
		self.assertEqual(first_response.data['company_name'], 'Fit Hive')

		second_response = self.client.post(
			reverse('dashboard:site-settings'),
			{'company_name': 'Fit Hive Updated'},
			format='json',
		)
		self.assertEqual(second_response.status_code, status.HTTP_200_OK)
		self.assertEqual(second_response.data['company_name'], 'Fit Hive Updated')
