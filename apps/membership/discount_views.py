"""Discount CRUD, preview, and public coupon validation views."""
from __future__ import annotations

from django.core.cache import cache
from django.db.models import Count
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access.permissions import HasFeatureMethodPermission
from apps.membership.discount_serializers import (
    DiscountPreviewSerializer,
    DiscountSerializer,
)
from apps.membership.models import Discount, Member, MemberPackage
from apps.membership.services.discount_engine import (
    apply_discounts_for_payment,
)
from apps.tenancy.services import tenant_has_feature
from utils.base_view import ModelCRUDView
from utils.list_mixins import SearchFilterSortPaginationMixin


class DiscountView(SearchFilterSortPaginationMixin, ModelCRUDView):
    """CRUD for package discounts."""

    feature_key = "discount"
    queryset = Discount.objects.filter(is_deleted=False).prefetch_related("conditions").annotate(
        _usage_count=Count("usages")
    )
    serializer_class = DiscountSerializer
    permission_classes = [HasFeatureMethodPermission]
    filterset_fields = ["is_active", "discount_type", "application_mode"]
    search_fields = ["name", "coupon_code", "description"]
    ordering_fields = ["id", "priority", "name", "created_at", "starts_at", "ends_at"]
    ordering = ["priority", "id"]

    def get_queryset(self):
        from apps.membership.services.discount_engine import expire_ended_discounts

        expire_ended_discounts()
        return super().get_queryset()


class DiscountPreviewAPIView(APIView):
    """POST /discounts/preview/ — compute discounted total for a cart."""

    feature_key = "discount"
    permission_classes = [IsAuthenticated, HasFeatureMethodPermission]

    def post(self, request):
        ser = DiscountPreviewSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        package = MemberPackage.objects.filter(pk=data["package_id"], is_deleted=False).first()
        if package is None:
            return Response({"package_id": "Package not found."}, status=status.HTTP_404_NOT_FOUND)
        member = None
        member_id = data.get("member_id")
        if member_id:
            member = Member.objects.filter(pk=member_id, is_deleted=False).first()
        result = apply_discounts_for_payment(
            package=package,
            member=member or Member(membership_type="package"),
            coverage_months=data.get("coverage_months") or [],
            selected_addon_names=data.get("selected_addon_names"),
            coupon_code=data.get("coupon_code") or None,
            feature_enabled=True,
        )
        if result is None:
            return Response({"detail": "Discount feature unavailable."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result.as_dict())


class PublicValidateCouponAPIView(APIView):
    """POST /discounts/validate-coupon/ — public coupon check (rate-limited)."""

    permission_classes = [AllowAny]

    def post(self, request):
        tenant = getattr(request, "tenant", None)
        if tenant is None or not tenant_has_feature(tenant, "discount"):
            return Response({"valid": False, "detail": "Discounts are not available."}, status=status.HTTP_404_NOT_FOUND)

        # Simple per-IP rate limit: 30 requests / minute
        ip = request.META.get("REMOTE_ADDR", "unknown")
        cache_key = f"discount_coupon_rl:{getattr(tenant, 'schema_name', '')}:{ip}"
        hits = cache.get(cache_key, 0)
        if hits >= 30:
            return Response({"detail": "Too many requests."}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        cache.set(cache_key, hits + 1, timeout=60)

        code = str(request.data.get("coupon_code") or "").strip()
        package_id = request.data.get("package_id")
        if not code or not package_id:
            return Response(
                {"valid": False, "detail": "coupon_code and package_id are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        package = MemberPackage.objects.filter(
            pk=package_id, is_deleted=False, is_active=True, is_published=True
        ).first()
        if package is None:
            return Response({"valid": False, "detail": "Invalid package."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            result = apply_discounts_for_payment(
                package=package,
                member=Member(membership_type="package"),
                coverage_months=request.data.get("coverage_months") or [],
                selected_addon_names=request.data.get("selected_addon_names"),
                coupon_code=code,
                feature_enabled=True,
            )
        except Exception:
            return Response({"valid": False, "detail": "Invalid or ineligible coupon code."})

        if result is None or not result.applied:
            return Response({"valid": False, "detail": "Invalid or ineligible coupon code."})
        return Response({"valid": True, **result.as_dict()})
