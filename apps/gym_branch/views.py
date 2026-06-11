from django.db import connection
from django.utils import timezone

from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access.permissions import HasFeatureMethodPermission
from utils.limits import total_capacity_exceeded
from utils.base_view import ModelCRUDView
from utils.cache_helpers import (
    PUBLIC_BRANCH_TTL,
    PUBLIC_BRANDING_TTL,
    get_cached_value,
    public_branches_key,
    public_branding_key,
)
from utils.query_optimization import (
    optimized_branch_queryset,
    optimized_branch_shift_request_queryset,
)

from .models import Branch, BranchShiftRequest
from .serializers import (
    BranchMinimalSerializer,
    BranchSerializer,
    BranchShiftRequestSerializer,
)

FEATURE_KEY = "branches"


class BranchView(ModelCRUDView):
    """CRUD for gym branches. Enforces the tenant's max_branches limit."""

    feature_key = FEATURE_KEY
    queryset = Branch.objects.all().order_by("display_order", "id")
    serializer_class = BranchSerializer
    permission_classes = [HasFeatureMethodPermission]

    def get_queryset(self):
        return optimized_branch_queryset(super().get_queryset())

    def _create(self, request):
        tenant = getattr(connection, "tenant", None)
        if tenant is not None:
            limit_error = total_capacity_exceeded(
                Branch.objects,
                "max_branches",
                limit_type="branches",
            )
            if limit_error is not None:
                return Response(limit_error, status=status.HTTP_403_FORBIDDEN)
        return super()._create(request)


class PublicBranchListView(APIView):
    """Public, read-only list of branches for the marketing site."""

    permission_classes = [AllowAny]

    def get(self, request):
        schema_name = connection.schema_name
        homepage = request.query_params.get("homepage") in ("1", "true", "True")
        cache_key = public_branches_key(schema_name, minimal=False, homepage=homepage)

        def load():
            queryset = optimized_branch_queryset(
                Branch.objects.filter(is_active=True).order_by("display_order", "id")
            )
            if homepage:
                queryset = queryset.filter(show_on_homepage=True)
            return BranchSerializer(queryset, many=True).data

        return Response(get_cached_value(cache_key, PUBLIC_BRANCH_TTL, load))


class PublicBranchMinimalListView(APIView):
    """Public minimal branch list for dropdowns (e.g. contact form)."""

    permission_classes = [AllowAny]

    def get(self, request):
        schema_name = connection.schema_name
        cache_key = public_branches_key(schema_name, minimal=True)

        def load():
            queryset = Branch.objects.filter(is_active=True).order_by(
                "display_order", "id"
            )
            return BranchMinimalSerializer(queryset, many=True).data

        return Response(get_cached_value(cache_key, PUBLIC_BRANCH_TTL, load))


class BranchManagerOptionsView(APIView):
    """List tenant users that can be assigned as a branch manager."""

    feature_key = FEATURE_KEY
    permission_classes = [HasFeatureMethodPermission]

    def get(self, request):
        from apps.identity.models import User

        users = User.objects.filter(is_active=True).order_by("email")
        data = [
            {
                "id": user.id,
                "name": getattr(user, "full_name", None) or user.email,
                "email": user.email,
            }
            for user in users
        ]
        return Response(data)



class BranchShiftRequestActions:
    actions = {
        "approve": lambda self, req, pk: self._decide(req, pk, "approved"),
        "reject": lambda self, req, pk: self._decide(req, pk, "rejected"),
    }

    def _decide(self, request, pk, new_status):
        try:
            shift = BranchShiftRequest.objects.get(pk=pk)
        except BranchShiftRequest.DoesNotExist:
            return Response(
                {"detail": "Shift request not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if shift.status != "pending":
            return Response(
                {"detail": f"This request has already been {shift.status}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        shift.status = new_status
        shift.decision_note = request.data.get("decision_note", "")
        shift.reviewed_by = request.user
        shift.reviewed_at = timezone.now()
        shift.save(
            update_fields=[
                "status",
                "decision_note",
                "reviewed_by",
                "reviewed_at",
                "updated_at",
            ]
        )

        if new_status == "approved":
            target = shift.member or shift.trainer
            if target is not None:
                target.branch = shift.to_branch
                target.save(update_fields=["branch", "updated_at"])

        return Response(BranchShiftRequestSerializer(shift).data)


class BranchShiftRequestView(BranchShiftRequestActions, ModelCRUDView):
    """Tenant-side management of branch shift requests (list / approve / reject)."""

    feature_key = FEATURE_KEY
    queryset = optimized_branch_shift_request_queryset(
        BranchShiftRequest.objects.all()
    ).order_by("-created_at")
    serializer_class = BranchShiftRequestSerializer
    permission_classes = [HasFeatureMethodPermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        status_param = self.request.query_params.get("status")
        if status_param:
            queryset = queryset.filter(status=status_param)
        return queryset


class MyBranchShiftRequestView(APIView):
    """Self-service endpoint for members/trainers to submit & view shift requests."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        member_id = request.query_params.get("member")
        trainer_id = request.query_params.get("trainer")
        queryset = optimized_branch_shift_request_queryset(
            BranchShiftRequest.objects.all()
        ).order_by("-created_at")
        if member_id:
            queryset = queryset.filter(member_id=member_id)
        elif trainer_id:
            queryset = queryset.filter(trainer_id=trainer_id)
        else:
            return Response([])
        return Response(BranchShiftRequestSerializer(queryset, many=True).data)

    def post(self, request):
        serializer = BranchShiftRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()

        # Capture the current branch as the origin of the request.
        source = instance.member or instance.trainer
        if source is not None and source.branch_id:
            instance.from_branch_id = source.branch_id
            instance.save(update_fields=["from_branch", "updated_at"])

        return Response(
            BranchShiftRequestSerializer(instance).data,
            status=status.HTTP_201_CREATED,
        )
