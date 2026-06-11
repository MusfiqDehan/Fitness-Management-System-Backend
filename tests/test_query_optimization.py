"""Query-count regression tests for optimized list endpoints."""

from django.db import connection
from django.utils import timezone
from django_tenants.utils import schema_context
from rest_framework import status
from rest_framework.test import APITestCase, APIRequestFactory, force_authenticate

from apps.access.models import Role, UserRole
from apps.billing.models import PaymentTransaction
from apps.dashboard.views import PackageListAPIView, DashboardContactListAPIView
from apps.gym_branch.models import Branch, BranchShiftRequest, Facility
from apps.gym_branch.views import BranchView, PublicBranchListView
from apps.identity.models import User
from apps.membership.models import Member, MemberPackage, Payment
from apps.quick_action.models import Contact, Package, PackageFeature
from apps.tenancy.models import Domain, Tenant
from apps.tenancy.views import TenantAdminListAPIView
from apps.trainer.models import TrainerClass, TrainerInvitation, TrainerProfile, TrainerSchedule
from apps.trainer.views import (
    TrainerClassView,
    TrainerInvitationView,
    TrainerProfileView,
    TrainerScheduleView,
)
from apps.billing.views import PaymentAPIView
from apps.membership.views import PaymentView

from tests.query_test_helpers import TenantQueryTestMixin


class BranchListQueryCountTests(TenantQueryTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.factory = APIRequestFactory()
        self.enable_feature(self.tenant, "branches")
        self.admin, _ = User.objects.get_or_create(
            email="admin@queryopt.test",
            defaults={"is_superuser": True, "is_staff": True, "is_active": True},
        )
        Branch.objects.all().delete()
        Member.objects.all().delete()
        for index in range(5):
            branch = Branch.objects.create(name=f"Branch {index}", is_active=True)
            facility = Facility.objects.create(name=f"Facility {index}")
            branch.facilities.add(facility)
            Member.objects.create(
                full_name=f"Member {index}",
                phone_number=f"017000000{index}",
                branch=branch,
            )

    def test_branch_list_query_count_is_bounded(self):
        request = self.factory.get("/branch/")
        force_authenticate(request, user=self.admin)

        def call():
            response = BranchView.as_view()(request)
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assert_query_count_bounded(call, max_queries=15)

    def test_public_branch_list_query_count_is_bounded(self):
        def call():
            response = PublicBranchListView.as_view()(request := self.factory.get("/public/branches/"))
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assert_query_count_bounded(call, max_queries=10)


class PaymentListQueryCountTests(TenantQueryTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.factory = APIRequestFactory()
        self.enable_feature(self.tenant, "payments")
        self.admin, _ = User.objects.get_or_create(
            email="payments@queryopt.test",
            defaults={"is_superuser": True, "is_staff": True, "is_active": True},
        )
        branch = Branch.objects.create(name="Main", is_active=True)
        package = MemberPackage.objects.create(
            name="Basic",
            package_type="monthly",
            duration_in_days=30,
            price="1000.00",
        )
        Payment.objects.all().delete()
        Member.objects.all().delete()
        for index in range(5):
            member = Member.objects.create(
                full_name=f"Payer {index}",
                phone_number=f"018000000{index}",
                branch=branch,
                member_package=package,
            )
            payment = Payment.objects.create(
                member=member,
                payment_type="package",
                amount="500.00",
                payment_method="cash",
                payment_status="paid",
            )
            PaymentTransaction.objects.create(
                tran_id=f"TX-{index}-{timezone.now().timestamp()}",
                gateway_slug="sslcommerz",
                amount="500.00",
                status=PaymentTransaction.STATUS_SUCCESS,
                source_payment=payment,
            )

    def test_billing_payment_list_query_count_is_bounded(self):
        request = self.factory.get("/billing/payments/")
        force_authenticate(request, user=self.admin)

        def call():
            response = PaymentAPIView.as_view()(request)
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assert_query_count_bounded(call, max_queries=20)

    def test_membership_payment_list_query_count_is_bounded(self):
        request = self.factory.get("/membership/payments/")
        force_authenticate(request, user=self.admin)

        def call():
            response = PaymentView.as_view()(request)
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assert_query_count_bounded(call, max_queries=20)


class TrainerProfileListQueryCountTests(TenantQueryTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.factory = APIRequestFactory()
        self.enable_feature(self.tenant, "instructors")
        self.admin, _ = User.objects.get_or_create(
            email="trainer@queryopt.test",
            defaults={"is_superuser": True, "is_staff": True, "is_active": True},
        )
        branch = Branch.objects.create(name="Trainer Branch", is_active=True)
        TrainerProfile.objects.all().delete()
        TrainerInvitation.objects.all().delete()
        for index in range(5):
            user = User.objects.create_user(
                email=f"trainer{index}@queryopt.test",
                password="Test@1234",
                role="trainer",
            )
            TrainerProfile.objects.create(
                user=user,
                username=f"trainer{index}",
                branch=branch,
            )
            TrainerInvitation.objects.create(
                invited_email=user.email,
                branch=branch,
                invited_by=self.admin,
            )

    def test_trainer_profile_list_query_count_is_bounded(self):
        request = self.factory.get("/trainer/profile/")
        force_authenticate(request, user=self.admin)

        def call():
            response = TrainerProfileView.as_view()(request)
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assert_query_count_bounded(call, max_queries=20)


class TenantAdminListQueryCountTests(APITestCase):
    SCHEMA_NAME = "tenant_admin_list_test"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.factory = APIRequestFactory()
        with schema_context("public"):
            Tenant.objects.filter(schema_name=cls.SCHEMA_NAME).delete()
            cls.child_tenant = Tenant.objects.create(
                schema_name=cls.SCHEMA_NAME,
                name="Child Tenant",
                slug="child-query-opt",
                code="CHILDQOPT",
                owner_email="child@queryopt.test",
                billing_email="child@queryopt.test",
                status="active",
            )
            Domain.objects.create(
                domain="child-query-opt.test",
                tenant=cls.child_tenant,
                is_primary=True,
            )
            cls.platform_admin = User.objects.create_superuser(
                email="platform@queryopt.test",
                password="Test@1234",
            )
        connection.set_schema_to_public()

    @classmethod
    def tearDownClass(cls):
        connection.set_schema_to_public()
        super().tearDownClass()
        with schema_context("public"):
            tenant = Tenant.objects.filter(schema_name=cls.SCHEMA_NAME).first()
            if tenant is not None:
                tenant.delete(force_drop=True)

    def test_tenant_admin_list_query_count_is_bounded(self):
        from django.test.utils import CaptureQueriesContext

        request = self.factory.get("/admin/tenants/")
        force_authenticate(request, user=self.platform_admin)

        def call():
            response = TenantAdminListAPIView.as_view()(request)
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        with CaptureQueriesContext(connection) as context:
            call()
        self.assertLessEqual(len(context), 25)


class DashboardPackageListQueryCountTests(TenantQueryTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.factory = APIRequestFactory()
        self.enable_feature(self.tenant, "members.packages")
        self.admin, _ = User.objects.get_or_create(
            email="packages@queryopt.test",
            defaults={"is_superuser": True, "is_staff": True, "is_active": True},
        )
        Package.objects.all().delete()
        for index in range(5):
            package = Package.objects.create(
                name=f"Package {index}",
                price=100 + index,
                duration="1 month",
            )
            PackageFeature.objects.create(package=package, feature=f"Feature {index}")

    def test_dashboard_package_list_query_count_is_bounded(self):
        request = self.factory.get("/dashboard/packages/")
        force_authenticate(request, user=self.admin)

        def call():
            response = PackageListAPIView.as_view()(request)
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assert_query_count_bounded(call, max_queries=15)


class MediumPriorityListQueryCountTests(TenantQueryTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.factory = APIRequestFactory()
        self.admin, _ = User.objects.get_or_create(
            email="medium@queryopt.test",
            defaults={"is_superuser": True, "is_staff": True, "is_active": True},
        )
        self.branch = Branch.objects.create(name="Medium Branch", is_active=True)
        self.member = Member.objects.create(
            full_name="Shift Member",
            phone_number="01900000001",
            branch=self.branch,
        )
        self.trainer_user = User.objects.create_user(
            email="shift-trainer@queryopt.test",
            password="Test@1234",
            role="trainer",
        )
        self.trainer = TrainerProfile.objects.create(
            user=self.trainer_user,
            username="shift-trainer",
            branch=self.branch,
        )
        self.enable_feature(self.tenant, "branches")
        self.enable_feature(self.tenant, "instructors")
        self.enable_feature(self.tenant, "crm.contacts")

    def test_branch_shift_request_list_query_count_is_bounded(self):
        from apps.gym_branch.views import BranchShiftRequestView

        target = Branch.objects.create(name="Target Branch", is_active=True)
        for index in range(3):
            BranchShiftRequest.objects.create(
                member=self.member,
                from_branch=self.branch,
                to_branch=target,
                reason=f"Reason {index}",
            )
        request = self.factory.get("/branch/shift-requests/")
        force_authenticate(request, user=self.admin)

        def call():
            response = BranchShiftRequestView.as_view()(request)
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assert_query_count_bounded(call, max_queries=15)

    def test_user_role_list_query_count_is_bounded(self):
        role = Role.objects.create(name="Staff", slug="staff")
        UserRole.objects.all().delete()
        for index in range(3):
            user = User.objects.create_user(
                email=f"staff{index}@queryopt.test",
                password="Test@1234",
                role="staff",
            )
            UserRole.objects.create(
                user_id=user.id,
                user_email=user.email,
                role=role,
                branch=self.branch,
            )
        from apps.access.views import UserRoleListCreateView

        request = self.factory.get("/access/user-roles/")
        force_authenticate(request, user=self.admin)

        def call():
            response = UserRoleListCreateView.as_view()(request)
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assert_query_count_bounded(call, max_queries=15)

    def test_trainer_invitation_list_query_count_is_bounded(self):
        TrainerInvitation.objects.all().delete()
        for index in range(3):
            TrainerInvitation.objects.create(
                invited_email=f"invite{index}@queryopt.test",
                branch=self.branch,
                invited_by=self.admin,
            )
        request = self.factory.get("/trainer/invitations/")
        force_authenticate(request, user=self.admin)

        def call():
            response = TrainerInvitationView.as_view()(request)
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assert_query_count_bounded(call, max_queries=15)

    def test_trainer_class_list_query_count_is_bounded(self):
        TrainerClass.objects.all().delete()
        for index in range(3):
            TrainerClass.objects.create(
                trainer=self.trainer,
                name=f"Class {index}",
            )
        request = self.factory.get("/trainer/classes/")
        force_authenticate(request, user=self.admin)

        def call():
            response = TrainerClassView.as_view()(request)
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assert_query_count_bounded(call, max_queries=15)

    def test_trainer_schedule_list_query_count_is_bounded(self):
        trainer_class = TrainerClass.objects.create(trainer=self.trainer, name="Yoga")
        TrainerSchedule.objects.all().delete()
        for index in range(3):
            TrainerSchedule.objects.create(
                trainer_class=trainer_class,
                trainer=self.trainer,
                day_of_week="monday",
                start_time="09:00",
                end_time="10:00",
            )
        request = self.factory.get("/trainer/schedules/")
        force_authenticate(request, user=self.admin)

        def call():
            response = TrainerScheduleView.as_view()(request)
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assert_query_count_bounded(call, max_queries=15)

    def test_dashboard_contact_list_query_count_is_bounded(self):
        Contact.objects.all().delete()
        for index in range(3):
            Contact.objects.create(
                name=f"Contact {index}",
                email=f"contact{index}@example.com",
                phone=f"016000000{index}",
                subject="Hello",
                message="Message",
                preferred_branch=self.branch,
            )
        request = self.factory.get("/dashboard/contacts/")
        force_authenticate(request, user=self.admin)

        def call():
            response = DashboardContactListAPIView.as_view()(request)
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assert_query_count_bounded(call, max_queries=15)


class ModelIndexTests(APITestCase):
    def test_high_priority_indexes_are_declared(self):
        from apps.membership.models import Attendance, Member, Payment
        from apps.reminder.models import Notification
        from apps.tenancy.models import TenantFeatureFlag, TenantSubscriptionInvoice

        member_index_names = {index.name for index in Member._meta.indexes}
        self.assertIn("idx_member_branch_active_end", member_index_names)
        self.assertIn("idx_member_branch_created", member_index_names)

        payment_index_names = {index.name for index in Payment._meta.indexes}
        self.assertIn("idx_payment_member_date", payment_index_names)

        attendance_index_names = {index.name for index in Attendance._meta.indexes}
        self.assertIn("idx_attendance_member_checkin", attendance_index_names)
        self.assertIn("idx_attendance_open_session", attendance_index_names)

        notification_index_names = {index.name for index in Notification._meta.indexes}
        self.assertIn("idx_notif_recip_created", notification_index_names)

        feature_flag_index_names = {index.name for index in TenantFeatureFlag._meta.indexes}
        self.assertIn("idx_tff_grace_expiry", feature_flag_index_names)

        invoice_index_names = {
            index.name for index in TenantSubscriptionInvoice._meta.indexes
        }
        self.assertIn("idx_tsubinv_tenant_created", invoice_index_names)
