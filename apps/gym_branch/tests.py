"""Tenant-schema tests for the gym_branch app.

Covers branch CRUD limit enforcement, branch shift-request approval
(which moves the member/trainer to the target branch), rejection, and the
public (AllowAny) minimal branch listing.

Views are exercised directly via ``APIRequestFactory`` + ``force_authenticate``
to avoid host-header tenant routing. A superuser is used so the feature-gated
permission (``HasFeatureMethodPermission``) is satisfied without seeding RBAC.
"""
from django.db import connection
from django_tenants.utils import schema_context
from rest_framework import status
from rest_framework.test import APITestCase, APIRequestFactory, force_authenticate

from apps.identity.models import User
from apps.membership.models import Member
from apps.tenancy.models import Domain, Feature, Tenant, TenantFeatureFlag

from .models import Branch, BranchShiftRequest
from .views import (
    BranchShiftRequestView,
    BranchView,
    PublicBranchMinimalListView,
)


class GymBranchTenantTests(APITestCase):
    SCHEMA_NAME = "tenant_branch_test"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with schema_context("public"):
            # Clean any schema/tenant left over from an aborted prior run.
            Tenant.objects.filter(schema_name=cls.SCHEMA_NAME).delete()
            with connection.cursor() as cur:
                cur.execute(
                    'DROP SCHEMA IF EXISTS "%s" CASCADE' % cls.SCHEMA_NAME
                )
            cls.tenant = Tenant.objects.create(
                schema_name="tenant_branch_test",
                name="Branch Tenant",
                slug="branch-tenant",
                code="BRANCHTEST",
                owner_email="owner@branch.test",
                billing_email="owner@branch.test",
                status="active",
                is_trial=False,
                max_branches=1,
            )
            Domain.objects.create(
                domain="branchtenant.localhost",
                tenant=cls.tenant,
                is_primary=True,
            )
            # Enable the 'branches' feature for this tenant (package gate).
            feature, _ = Feature.objects.get_or_create(
                key="branches",
                defaults={"name": "Branches", "sort_order": 5},
            )
            TenantFeatureFlag.objects.update_or_create(
                tenant=cls.tenant,
                feature=feature,
                defaults={
                    "is_enabled": True,
                    "source": TenantFeatureFlag.SOURCE_OVERRIDE,
                },
            )

    @classmethod
    def tearDownClass(cls):
        # Close the class-level test transaction first so the schema drop does
        # not run with deferred trigger events still pending.
        connection.set_schema_to_public()
        super().tearDownClass()
        with schema_context("public"):
            tenant = Tenant.objects.filter(schema_name=cls.SCHEMA_NAME).first()
            if tenant is not None:
                tenant.delete(force_drop=True)
            with connection.cursor() as cur:
                cur.execute(
                    'DROP SCHEMA IF EXISTS "%s" CASCADE' % cls.SCHEMA_NAME
                )

    def setUp(self):
        self.factory = APIRequestFactory()
        connection.set_tenant(self.tenant)
        # Reset limit on the in-memory tenant (the view reads connection.tenant).
        self.tenant.max_branches = 1
        # Deterministic clean state per test (manual schema switching does not
        # get rolled back by the test transaction).
        BranchShiftRequest.objects.all().delete()
        Member.objects.all().delete()
        Branch.objects.all().delete()
        self.admin, _ = User.objects.get_or_create(
            email="admin@branch.test",
            defaults={
                "is_superuser": True,
                "is_staff": True,
                "is_active": True,
            },
        )
        self.main_branch = Branch.objects.create(name="Main Branch", is_active=True)

    def tearDown(self):
        connection.set_schema_to_public()

    # ── Branch limit enforcement ────────────────────────────────
    def test_create_branch_blocked_when_max_branches_reached(self):
        # Tenant max_branches=1 and one branch already exists.
        request = self.factory.post(
            "/branch/", {"name": "Second Branch"}, format="json"
        )
        force_authenticate(request, user=self.admin)
        response = BranchView.as_view()(request)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["code"], "LIMIT_EXCEEDED")
        self.assertEqual(response.data["limit_type"], "branches")
        self.assertEqual(Branch.objects.count(), 1)

    def test_create_branch_allowed_within_limit(self):
        self.tenant.max_branches = 5
        request = self.factory.post(
            "/branch/", {"name": "Downtown Branch"}, format="json"
        )
        force_authenticate(request, user=self.admin)
        response = BranchView.as_view()(request)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Branch.objects.count(), 2)

    # ── Shift request approval / rejection ──────────────────────
    def test_approving_shift_request_moves_member_to_target_branch(self):
        target = Branch.objects.create(name="North Branch", is_active=True)
        member = Member.objects.create(
            full_name="Jane Member",
            phone_number="+8801700000001",
            branch=self.main_branch,
        )
        shift = BranchShiftRequest.objects.create(
            member=member,
            from_branch=self.main_branch,
            to_branch=target,
            reason="Closer to home",
        )

        request = self.factory.post(
            f"/branch/shift-requests/{shift.id}/?action=approve",
            {"decision_note": "Approved"},
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = BranchShiftRequestView.as_view()(request, pk=shift.id)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        shift.refresh_from_db()
        member.refresh_from_db()
        self.assertEqual(shift.status, "approved")
        self.assertEqual(shift.reviewed_by_id, self.admin.id)
        self.assertEqual(member.branch_id, target.id)

    def test_rejecting_shift_request_keeps_member_branch(self):
        target = Branch.objects.create(name="South Branch", is_active=True)
        member = Member.objects.create(
            full_name="John Member",
            phone_number="+8801700000002",
            branch=self.main_branch,
        )
        shift = BranchShiftRequest.objects.create(
            member=member,
            from_branch=self.main_branch,
            to_branch=target,
        )

        request = self.factory.post(
            f"/branch/shift-requests/{shift.id}/?action=reject",
            {"decision_note": "Not now"},
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = BranchShiftRequestView.as_view()(request, pk=shift.id)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        shift.refresh_from_db()
        member.refresh_from_db()
        self.assertEqual(shift.status, "rejected")
        self.assertEqual(member.branch_id, self.main_branch.id)

    def test_deciding_already_decided_request_returns_400(self):
        target = Branch.objects.create(name="East Branch", is_active=True)
        member = Member.objects.create(
            full_name="Amy Member",
            phone_number="+8801700000003",
            branch=self.main_branch,
        )
        shift = BranchShiftRequest.objects.create(
            member=member,
            from_branch=self.main_branch,
            to_branch=target,
            status="approved",
        )

        request = self.factory.post(
            f"/branch/shift-requests/{shift.id}/?action=approve",
            {},
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = BranchShiftRequestView.as_view()(request, pk=shift.id)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # ── Public minimal listing ──────────────────────────────────
    def test_public_minimal_branch_list_is_open_and_filters_inactive(self):
        Branch.objects.create(name="Hidden Branch", is_active=False)
        request = self.factory.get("/branch/public/branches/minimal/")
        response = PublicBranchMinimalListView.as_view()(request)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [row["name"] for row in response.data]
        self.assertIn("Main Branch", names)
        self.assertNotIn("Hidden Branch", names)
