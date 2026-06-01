import json
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from .models import (
	Banner,
	Blog,
	BlogCategory,
	Package,
	PackageAddOn,
	PackageFeature,
)


TEST_MEDIA_ROOT = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class MainAppExplicitAPIViewTests(APITestCase):
	banner_list_url = 'quick_action:banner-list'
	banner_create_url = 'quick_action:banner-create'
	banner_detail_url = 'quick_action:banner-detail'
	banner_update_url = 'quick_action:banner-update'
	banner_delete_url = 'quick_action:banner-delete'
	blog_category_create_url = 'quick_action:blog-category-create'
	blog_category_list_url = 'quick_action:blog-category-list'
	blog_category_detail_url = 'quick_action:blog-category-detail'
	blog_category_update_url = 'quick_action:blog-category-update'
	blog_category_delete_url = 'quick_action:blog-category-delete'
	package_list_url = 'quick_action:public-packages-list'
	package_detail_url = 'quick_action:public-packages-detail'

	@classmethod
	def tearDownClass(cls):
		super().tearDownClass()
		shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

	def _banner_file(self, name='banner.txt', content=b'banner-content'):
		return SimpleUploadedFile(name, content, content_type='text/plain')

	def _create_banner(self, index, is_active=True):
		return Banner.objects.create(
			background_type='image',
			background_file=self._banner_file(name=f'banner-{index}.txt'),
			title1=f'Small {index}',
			title2=f'Big {index}',
			title3=f'Medium {index}',
			fitness_name=f'Fitness {index}',
			is_active=is_active,
		)

	def _create_package(self, index, is_active=True):
		package = Package.objects.create(
			name=f'Package {index}',
			duration='1 month',
			price='99.99',
			display_order=index,
			description=f'Package description {index}',
			is_popular=index % 2 == 0,
			is_active=is_active,
		)
		PackageFeature.objects.create(package=package, feature=f'Feature {index}')
		PackageAddOn.objects.create(
			package=package,
			name=f'Addon {index}',
			price='9.99',
			description=f'Addon description {index}',
			is_active=True,
		)
		return package

	def _create_blog(self, index, category):
		return Blog.objects.create(
			title=f'Blog {index}',
			image=SimpleUploadedFile(
				f'blog-{index}.txt',
				b'blog-content',
				content_type='text/plain',
			),
			category=category,
			excerpt=f'Excerpt {index}',
			description=f'Description {index}',
			status='published',
			published_date=timezone.now(),
		)

	def test_banner_explicit_crud_endpoints_preserve_pagination_and_methods(self):
		for index in range(11):
			self._create_banner(index=index)
		self._create_banner(index=99, is_active=False)

		list_response = self.client.get(reverse(self.banner_list_url))

		self.assertEqual(list_response.status_code, status.HTTP_200_OK)
		self.assertEqual(list_response.data['count'], 11)
		self.assertEqual(len(list_response.data['results']), 10)

		create_response = self.client.post(
			reverse(self.banner_create_url),
			{
				'background_type': 'image',
				'background_file': self._banner_file(name='new-banner.txt'),
				'title1': 'New small title',
				'title2': 'New big title',
				'title3': 'New medium title',
				'fitness_name': 'New Fitness',
				'is_active': True,
			},
			format='multipart',
		)

		self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
		banner_id = create_response.data['id']

		detail_response = self.client.get(reverse(self.banner_detail_url, args=[banner_id]))
		self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
		self.assertEqual(detail_response.data['fitness_name'], 'New Fitness')

		patch_response = self.client.patch(
			reverse(self.banner_update_url, args=[banner_id]),
			{'title1': 'Updated small title'},
			format='multipart',
		)

		self.assertEqual(patch_response.status_code, status.HTTP_200_OK)
		self.assertEqual(patch_response.data['title1'], 'Updated small title')

		delete_response = self.client.delete(reverse(self.banner_delete_url, args=[banner_id]))
		self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)
		self.assertFalse(Banner.objects.filter(pk=banner_id).exists())

	def test_blog_category_explicit_api_views_support_put_and_unique_validation(self):
		create_response = self.client.post(
			reverse(self.blog_category_create_url),
			{'name': 'Training Tips'},
			format='json',
		)

		self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
		category_id = create_response.data['id']

		list_response = self.client.get(reverse(self.blog_category_list_url))
		self.assertEqual(list_response.status_code, status.HTTP_200_OK)
		self.assertEqual(list_response.data['count'], 1)

		detail_response = self.client.get(reverse(self.blog_category_detail_url, args=[category_id]))
		self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
		self.assertEqual(detail_response.data['name'], 'Training Tips')

		put_response = self.client.put(
			reverse(self.blog_category_update_url, args=[category_id]),
			{'name': 'Nutrition Advice'},
			format='json',
		)

		self.assertEqual(put_response.status_code, status.HTTP_200_OK)
		self.assertEqual(put_response.data['name'], 'Nutrition Advice')

		duplicate_response = self.client.post(
			reverse(self.blog_category_create_url),
			{'name': ' nutrition advice '},
			format='json',
		)

		self.assertEqual(duplicate_response.status_code, status.HTTP_400_BAD_REQUEST)
		self.assertIn('name', duplicate_response.data)

		delete_response = self.client.delete(reverse(self.blog_category_delete_url, args=[category_id]))
		self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)
		self.assertFalse(BlogCategory.objects.filter(pk=category_id).exists())

	def test_package_public_api_views_preserve_pagination_and_nested_response_shape(self):
		for index in range(11):
			self._create_package(index=index)
		inactive_package = self._create_package(index=99, is_active=False)

		list_response = self.client.get(reverse(self.package_list_url))

		self.assertEqual(list_response.status_code, status.HTTP_200_OK)
		self.assertEqual(list_response.data['count'], 11)
		self.assertEqual(len(list_response.data['results']), 10)
		self.assertIn('features', list_response.data['results'][0])
		self.assertIn('addons', list_response.data['results'][0])

		active_package = Package.objects.filter(is_active=True).order_by('display_order', 'name').first()
		detail_response = self.client.get(reverse(self.package_detail_url, args=[active_package.pk]))

		self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
		self.assertEqual(detail_response.data['id'], active_package.pk)
		self.assertEqual(detail_response.data['features'][0]['feature'], f'Feature {active_package.display_order}')
		self.assertEqual(detail_response.data['addons'][0]['name'], f'Addon {active_package.display_order}')

		inactive_detail_response = self.client.get(reverse(self.package_detail_url, args=[inactive_package.pk]))
		self.assertEqual(inactive_detail_response.status_code, status.HTTP_404_NOT_FOUND)

	def test_public_package_list_stays_within_query_budget(self):
		for index in range(5):
			self._create_package(index=index)

		with CaptureQueriesContext(connection) as queries:
			response = self.client.get(reverse(self.package_list_url))

		self.assertEqual(response.status_code, status.HTTP_200_OK)
		self.assertLessEqual(len(queries), 5)

	def test_public_blog_list_stays_within_query_budget(self):
		category = BlogCategory.objects.create(name='Performance Blog Category')
		for index in range(5):
			self._create_blog(index=index, category=category)

		with CaptureQueriesContext(connection) as queries:
			response = self.client.get('/api/blogs/')

		self.assertEqual(response.status_code, status.HTTP_200_OK)
		self.assertLessEqual(len(queries), 4)
