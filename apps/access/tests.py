from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.access import utils as access_utils
from apps.access.views import MyPermissionsView


class MyPermissionsViewTests(SimpleTestCase):
	def setUp(self):
		self.factory = APIRequestFactory()

	def test_uses_request_tenant_when_user_tenant_is_none(self):
		user = SimpleNamespace(
			id=7,
			email="member@example.com",
			full_name="Member User",
			role="staff",
			is_superuser=False,
			is_staff=False,
			tenant=None,
			is_authenticated=True,
		)
		request = self.factory.get("/api/v1/access/me/")
		request.tenant = SimpleNamespace(id=99)
		force_authenticate(request, user=user)

		fake_flags = [
			SimpleNamespace(feature=SimpleNamespace(key="crm.contacts"), is_effectively_enabled=True),
			SimpleNamespace(feature=SimpleNamespace(key="crm.inquiries"), is_effectively_enabled=True),
		]
		fake_qs = Mock()
		fake_qs.select_related.return_value = fake_flags

		with patch("apps.access.views.connection.schema_name", "tenant_a"), \
			 patch("apps.access.views.get_user_permission_map", return_value={"crm.contacts": "view", "crm.inquiries": "view"}), \
			 patch("apps.tenancy.services.get_tenant_enabled_feature_keys", return_value={"crm.contacts", "crm.inquiries"}), \
			 patch("apps.tenancy.services.custom_domain_effectively_enabled", return_value=False), \
			 patch("apps.access.views.UserRole.objects.filter") as user_roles, \
			 patch("apps.access.views.get_cached_value", side_effect=lambda _k, _t, factory: factory()):
			user_roles.return_value.select_related.return_value.values_list.return_value.distinct.return_value = []
			response = MyPermissionsView.as_view()(request)

		self.assertEqual(response.status_code, 200)
		self.assertIn("crm.contacts", response.data["enabled_features"])
		self.assertIn("crm.inquiries", response.data["enabled_features"])


class UserCanTests(SimpleTestCase):
	def test_prefers_active_schema_tenant_over_user_tenant(self):
		user = SimpleNamespace(is_authenticated=True, is_superuser=False, is_staff=False, role="staff", tenant=SimpleNamespace(id=1))
		current_tenant = SimpleNamespace(id=2)

		with patch("apps.access.utils.is_in_tenant_schema", return_value=True), \
			 patch("apps.access.utils._resolve_current_tenant", return_value=current_tenant), \
			 patch("apps.access.utils.tenant_has_feature", return_value=True) as has_feature, \
			 patch("apps.access.utils.get_user_permission_level", return_value="view"):
			allowed = access_utils.user_can(user, "crm.contacts", "view")

		self.assertTrue(allowed)
		has_feature.assert_called_once_with(current_tenant, "crm.contacts")
