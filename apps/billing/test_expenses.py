"""API and service tests for tenant Expense Manager."""
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import override_settings
from django_tenants.utils import schema_context
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIRequestFactory, APITestCase, force_authenticate

from apps.access.models import Role, RolePermission, UserRole
from apps.billing.expense_views import (
    ExpenseAPIView,
    ExpenseCategoryAPIView,
    ExpenseSummaryAPIView,
    ExpenseVoucherPdfAPIView,
)
from apps.billing.models import Expense, ExpenseCategory
from apps.billing.services.expense_voucher import (
    ensure_expense_voucher_no,
    render_expense_voucher_pdf,
)
from apps.billing.services.expenses import (
    assert_category_can_be_deleted,
    assert_category_name_unique,
    build_expense_summary,
    scope_expense_queryset,
    validate_attachment_file_url,
)
from apps.gym_branch.models import Branch
from apps.identity.models import User
from apps.tenancy.models import Domain, Feature, Tenant, TenantFeatureFlag


@override_settings(PUBLIC_DOMAIN="testserver")
class ExpenseManagerAPITests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        with schema_context("public"):
            cls.public, _ = Tenant.objects.get_or_create(
                schema_name="public",
                defaults=dict(
                    name="Public",
                    slug="public",
                    code="EXPUB001",
                    owner_email="root@expense.test",
                    billing_email="root@expense.test",
                    status="active",
                ),
            )
            Domain.objects.get_or_create(
                domain="testserver",
                tenant=cls.public,
                defaults={"is_primary": True},
            )
            cls.tenant = Tenant.objects.create(
                schema_name="expense_mgr_test",
                name="Expense Tenant",
                slug="expense-mgr",
                code="EXMGR001",
                owner_email="admin@expense.test",
                billing_email="admin@expense.test",
                status="active",
            )
            Domain.objects.create(
                domain="expense.testserver",
                tenant=cls.tenant,
                is_primary=True,
            )
            feature, _ = Feature.objects.get_or_create(
                key="expenses",
                defaults={"name": "Expenses"},
            )
            TenantFeatureFlag.objects.get_or_create(
                tenant=cls.tenant,
                feature=feature,
                defaults={
                    "is_enabled": True,
                    "source": TenantFeatureFlag.SOURCE_OVERRIDE,
                },
            )

        with schema_context(cls.tenant.schema_name):
            cls.admin = User.objects.create_superuser(
                email="admin@expense.test",
                password="StrongPass123!",
                tenant=cls.tenant,
            )
            cls.no_perm_user = User.objects.create_user(
                email="noperm@expense.test",
                password="StrongPass123!",
                tenant=cls.tenant,
                role="student",
            )
            cls.branch_manager = User.objects.create_user(
                email="bm@expense.test",
                password="StrongPass123!",
                tenant=cls.tenant,
                full_name="Branch Manager",
                role="student",
            )
            cls.branch_a = Branch.objects.create(
                name="Downtown",
                manager_id=cls.branch_manager.id,
            )
            cls.branch_b = Branch.objects.create(name="Uptown")
            bm_role = Role.objects.create(name="Branch Manager", slug="branch_manager")
            RolePermission.objects.create(
                role=bm_role,
                feature_key="expenses",
                permission_level="edit",
            )
            UserRole.objects.create(
                user_id=cls.branch_manager.id,
                user_email=cls.branch_manager.email,
                branch=cls.branch_a,
                role=bm_role,
            )

        cls.factory = APIRequestFactory()

    def _auth(self, request, user=None):
        force_authenticate(request, user=user or self.admin)
        request.tenant = self.tenant
        return request

    def test_create_and_list_category(self):
        with schema_context(self.tenant.schema_name):
            request = self._auth(
                self.factory.post(
                    "/api/v1/billing/expense-categories/",
                    {"name": "Utilities", "description": "Power and water"},
                    format="json",
                )
            )
            response = ExpenseCategoryAPIView.as_view()(request)
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            self.assertEqual(response.data["name"], "Utilities")

            list_req = self._auth(self.factory.get("/api/v1/billing/expense-categories/"))
            listed = ExpenseCategoryAPIView.as_view()(list_req)
            self.assertEqual(listed.status_code, status.HTTP_200_OK)
            results = listed.data.get("results", listed.data)
            self.assertTrue(any(c["name"] == "Utilities" for c in results))

    def test_duplicate_category_name_case_insensitive(self):
        with schema_context(self.tenant.schema_name):
            ExpenseCategory.objects.create(name="Utilities")
            request = self._auth(
                self.factory.post(
                    "/api/v1/billing/expense-categories/",
                    {"name": "utilities"},
                    format="json",
                )
            )
            response = ExpenseCategoryAPIView.as_view()(request)
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_delete_category_with_expenses_blocked(self):
        with schema_context(self.tenant.schema_name):
            cat = ExpenseCategory.objects.create(name="Rent")
            Expense.objects.create(
                title="Office rent",
                amount=Decimal("1000.00"),
                expense_date=date.today(),
                category=cat,
                receiver="Landlord",
            )
            request = self._auth(
                self.factory.delete(f"/api/v1/billing/expense-categories/{cat.id}/")
            )
            response = ExpenseCategoryAPIView.as_view()(request, pk=cat.id)
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertTrue(ExpenseCategory.objects.filter(pk=cat.id).exists())

    def test_delete_unused_category(self):
        with schema_context(self.tenant.schema_name):
            cat = ExpenseCategory.objects.create(name="Unused")
            request = self._auth(
                self.factory.delete(f"/api/v1/billing/expense-categories/{cat.id}/")
            )
            response = ExpenseCategoryAPIView.as_view()(request, pk=cat.id)
            self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
            self.assertFalse(ExpenseCategory.objects.filter(pk=cat.id).exists())

    def test_create_expense_with_receipt_and_pagination(self):
        with schema_context(self.tenant.schema_name):
            cat = ExpenseCategory.objects.create(name="Supplies")
            payload = {
                "title": "Cleaning supplies",
                "description": "Monthly restock",
                "receiver": "Vendor Co",
                "amount": "250.50",
                "expense_date": str(date.today()),
                "category": cat.id,
                "branch": self.branch_a.id,
                "attachments": [
                    {
                        "file_url": "/media/uploads/receipt-1.pdf",
                        "file_name": "receipt-1.pdf",
                        "kind": "receipt",
                    }
                ],
            }
            request = self._auth(
                self.factory.post("/api/v1/billing/expenses/", payload, format="json")
            )
            response = ExpenseAPIView.as_view()(request)
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            self.assertEqual(len(response.data["attachments"]), 1)
            self.assertEqual(response.data["attachments"][0]["kind"], "receipt")
            self.assertTrue(str(response.data["voucher_no"]).startswith("EXP-"))

            list_req = self._auth(
                self.factory.get("/api/v1/billing/expenses/?page_size=1")
            )
            listed = ExpenseAPIView.as_view()(list_req)
            self.assertEqual(listed.status_code, status.HTTP_200_OK)
            self.assertIn("results", listed.data)

    def test_filter_expenses_by_branch_and_search(self):
        with schema_context(self.tenant.schema_name):
            cat = ExpenseCategory.objects.create(name="FilterCat")
            Expense.objects.create(
                title="Branch A cost",
                amount=Decimal("10.00"),
                expense_date=date.today(),
                category=cat,
                branch=self.branch_a,
            )
            Expense.objects.create(
                title="Branch B cost",
                amount=Decimal("20.00"),
                expense_date=date.today(),
                category=cat,
                branch=self.branch_b,
            )
            Expense.objects.create(
                title="HQ cost",
                amount=Decimal("30.00"),
                expense_date=date.today(),
                category=cat,
                branch=None,
            )

            filtered_req = self._auth(
                self.factory.get(f"/api/v1/billing/expenses/?branch={self.branch_a.id}")
            )
            filtered = ExpenseAPIView.as_view()(filtered_req)
            results = filtered.data.get("results", filtered.data)
            titles = [r["title"] for r in results]
            self.assertIn("Branch A cost", titles)
            self.assertNotIn("Branch B cost", titles)
            self.assertNotIn("HQ cost", titles)

            searched_req = self._auth(
                self.factory.get("/api/v1/billing/expenses/?search=HQ")
            )
            searched = ExpenseAPIView.as_view()(searched_req)
            s_results = searched.data.get("results", searched.data)
            self.assertTrue(any(r["title"] == "HQ cost" for r in s_results))

    def test_soft_delete_expense_excluded_from_list(self):
        with schema_context(self.tenant.schema_name):
            cat = ExpenseCategory.objects.create(name="DelCat")
            expense = Expense.objects.create(
                title="To delete",
                amount=Decimal("5.00"),
                expense_date=date.today(),
                category=cat,
            )
            del_req = self._auth(
                self.factory.delete(f"/api/v1/billing/expenses/{expense.id}/")
            )
            response = ExpenseAPIView.as_view()(del_req, pk=expense.id)
            self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
            list_req = self._auth(self.factory.get("/api/v1/billing/expenses/"))
            listed = ExpenseAPIView.as_view()(list_req)
            results = listed.data.get("results", listed.data)
            self.assertFalse(any(r["id"] == expense.id for r in results))

    def test_summary_totals_and_categories(self):
        today = date.today()
        with schema_context(self.tenant.schema_name):
            cat_a = ExpenseCategory.objects.create(name="CatA")
            cat_b = ExpenseCategory.objects.create(name="CatB")
            Expense.objects.create(
                title="A1",
                amount=Decimal("100.00"),
                expense_date=today,
                category=cat_a,
            )
            Expense.objects.create(
                title="B1",
                amount=Decimal("50.00"),
                expense_date=today,
                category=cat_b,
            )
            Expense.objects.create(
                title="Old",
                amount=Decimal("999.00"),
                expense_date=today - timedelta(days=40),
                category=cat_b,
            )
            request = self._auth(self.factory.get("/api/v1/billing/expenses/summary/"))
            response = ExpenseSummaryAPIView.as_view()(request)
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(
                Decimal(str(response.data["total_expenses"])), Decimal("1149.00")
            )
            self.assertEqual(
                Decimal(str(response.data["current_month_total"])), Decimal("150.00")
            )
            self.assertEqual(response.data["highest_category"]["name"], "CatB")
            self.assertGreaterEqual(response.data["category_count"], 2)
            self.assertTrue(
                any(r["name"] == "CatA" for r in response.data["by_category"])
            )

    def test_empty_summary(self):
        with schema_context(self.tenant.schema_name):
            for expense in Expense.objects.all():
                expense.delete()
            request = self._auth(self.factory.get("/api/v1/billing/expenses/summary/"))
            response = ExpenseSummaryAPIView.as_view()(request)
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(
                Decimal(str(response.data["total_expenses"])), Decimal("0.00")
            )
            self.assertIsNone(response.data["highest_category"])
            self.assertEqual(response.data["by_category"], [])

    def test_branch_manager_sees_managed_and_null_branch_only(self):
        with schema_context(self.tenant.schema_name):
            cat = ExpenseCategory.objects.create(name="ScopeCat")
            Expense.objects.create(
                title="Mine",
                amount=Decimal("1.00"),
                expense_date=date.today(),
                category=cat,
                branch=self.branch_a,
            )
            Expense.objects.create(
                title="Other",
                amount=Decimal("2.00"),
                expense_date=date.today(),
                category=cat,
                branch=self.branch_b,
            )
            Expense.objects.create(
                title="Company",
                amount=Decimal("3.00"),
                expense_date=date.today(),
                category=cat,
                branch=None,
            )
            request = self._auth(
                self.factory.get("/api/v1/billing/expenses/"),
                user=self.branch_manager,
            )
            response = ExpenseAPIView.as_view()(request)
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            titles = [r["title"] for r in response.data.get("results", response.data)]
            self.assertIn("Mine", titles)
            self.assertIn("Company", titles)
            self.assertNotIn("Other", titles)

    def test_feature_disabled_blocks_list(self):
        with schema_context(self.tenant.schema_name):
            with patch("apps.access.utils.tenant_has_feature", return_value=False):
                request = self._auth(self.factory.get("/api/v1/billing/expenses/"))
                response = ExpenseAPIView.as_view()(request)
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_missing_rbac_blocks_user(self):
        with schema_context(self.tenant.schema_name):
            request = self._auth(
                self.factory.get("/api/v1/billing/expenses/"),
                user=self.no_perm_user,
            )
            response = ExpenseAPIView.as_view()(request)
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_invalid_attachment_url_rejected(self):
        with schema_context(self.tenant.schema_name):
            cat = ExpenseCategory.objects.create(name="AttCat")
            request = self._auth(
                self.factory.post(
                    "/api/v1/billing/expenses/",
                    {
                        "title": "Bad URL",
                        "amount": "10.00",
                        "expense_date": str(date.today()),
                        "category": cat.id,
                        "attachments": [
                            {"file_url": "not-a-url", "kind": "receipt"}
                        ],
                    },
                    format="json",
                )
            )
            response = ExpenseAPIView.as_view()(request)
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_service_helpers(self):
        with self.assertRaises(ValidationError):
            validate_attachment_file_url("bad")
        self.assertEqual(
            validate_attachment_file_url("/media/uploads/x.pdf"),
            "/media/uploads/x.pdf",
        )
        with schema_context(self.tenant.schema_name):
            assert_category_name_unique("UniqueName")
            cat = ExpenseCategory.objects.create(name="HelperCat")
            Expense.objects.create(
                title="H",
                amount=Decimal("1.00"),
                expense_date=date.today(),
                category=cat,
            )
            with self.assertRaises(ValidationError):
                assert_category_can_be_deleted(cat)
            qs = scope_expense_queryset(Expense.objects.all(), self.admin)
            summary = build_expense_summary(qs)
            self.assertIn("total_expenses", summary)

    def test_voucher_assigned_and_pdf_preview_download(self):
        with schema_context(self.tenant.schema_name):
            cat = ExpenseCategory.objects.create(name="VoucherCat")
            expense = Expense.objects.create(
                title="Office chairs",
                amount=Decimal("400.00"),
                expense_date=date.today(),
                category=cat,
                receiver="Furniture Co",
            )
            ensure_expense_voucher_no(expense)
            expense.refresh_from_db()
            self.assertEqual(expense.voucher_no, f"EXP-{expense.id:06d}")

            pdf_bytes = render_expense_voucher_pdf(
                expense, "Test Gym", "Admin User"
            )
            self.assertTrue(pdf_bytes.startswith(b"%PDF"))

            preview_req = self._auth(
                self.factory.get(f"/api/v1/billing/expenses/{expense.id}/voucher/")
            )
            preview = ExpenseVoucherPdfAPIView.as_view()(preview_req, pk=expense.id)
            self.assertEqual(preview.status_code, status.HTTP_200_OK)
            self.assertEqual(preview["Content-Type"], "application/pdf")
            self.assertIn("inline", preview["Content-Disposition"])

            download_req = self._auth(
                self.factory.get(
                    f"/api/v1/billing/expenses/{expense.id}/voucher/?download=1"
                )
            )
            download = ExpenseVoucherPdfAPIView.as_view()(
                download_req, pk=expense.id
            )
            self.assertEqual(download.status_code, status.HTTP_200_OK)
            self.assertIn("attachment", download["Content-Disposition"])
            self.assertIn(expense.voucher_no, download["Content-Disposition"])
