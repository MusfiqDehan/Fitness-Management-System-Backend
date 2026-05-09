"""Platform admin billing/packages management API.

All endpoints here run on the **public schema** and are gated by the
`platform.packages` platform-permission module:
- view  → required for GET
- edit  → required for POST / PUT / PATCH / DELETE
"""
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.tenancy.models import (
    Feature,
    PlatformPackage,
    PlatformPackageFeature,
)
from apps.tenancy.permissions import IsPlatformFeaturePermission

from .serializers import (
    FeatureSerializer,
    PackageFeatureBulkSerializer,
    PackageSerializer,
)


PACKAGE_VIEW_PERMS = [
    IsPlatformFeaturePermission.require("platform.packages", "view"),
]
PACKAGE_EDIT_PERMS = [
    IsPlatformFeaturePermission.require("platform.packages", "edit"),
]


class FeatureListAPIView(APIView):
    """GET /api/v1/billing/features/ — list all known features."""

    permission_classes = PACKAGE_VIEW_PERMS

    def get(self, request):
        features = Feature.objects.all().order_by("sort_order", "key")
        return Response(FeatureSerializer(features, many=True).data)


class PackageListCreateAPIView(APIView):
    """GET / POST /api/v1/billing/packages/."""

    def get_permissions(self):
        if self.request.method == "POST":
            return [perm() for perm in PACKAGE_EDIT_PERMS]
        return [perm() for perm in PACKAGE_VIEW_PERMS]

    def get(self, request):
        packages = (
            PlatformPackage.objects.all()
            .prefetch_related("package_features__feature")
            .order_by("sort_order", "price_monthly")
        )
        return Response(PackageSerializer(packages, many=True).data)

    def post(self, request):
        serializer = PackageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            package = serializer.save()
        return Response(
            PackageSerializer(package).data,
            status=status.HTTP_201_CREATED,
        )


class PackageDetailAPIView(APIView):
    """GET / PATCH / PUT / DELETE /api/v1/billing/packages/{pk}/."""

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [perm() for perm in PACKAGE_VIEW_PERMS]
        return [perm() for perm in PACKAGE_EDIT_PERMS]

    def _get_object(self, pk):
        return get_object_or_404(
            PlatformPackage.objects.prefetch_related("package_features__feature"),
            pk=pk,
        )

    def get(self, request, pk):
        return Response(PackageSerializer(self._get_object(pk)).data)

    def patch(self, request, pk):
        package = self._get_object(pk)
        serializer = PackageSerializer(package, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            package = serializer.save()
        return Response(PackageSerializer(package).data)

    def put(self, request, pk):
        package = self._get_object(pk)
        serializer = PackageSerializer(package, data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            package = serializer.save()
        return Response(PackageSerializer(package).data)

    def delete(self, request, pk):
        package = self._get_object(pk)
        package.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PackageFeaturesAPIView(APIView):
    """GET / PUT /api/v1/billing/packages/{pk}/features/.

    Manage which features a package includes. Idempotent bulk replacement.
    """

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [perm() for perm in PACKAGE_VIEW_PERMS]
        return [perm() for perm in PACKAGE_EDIT_PERMS]

    def get(self, request, pk):
        package = get_object_or_404(PlatformPackage, pk=pk)
        return Response({
            "package_id": package.id,
            "feature_ids": list(
                package.package_features.filter(is_enabled=True)
                .values_list("feature_id", flat=True)
            ),
        })

    def put(self, request, pk):
        package = get_object_or_404(PlatformPackage, pk=pk)
        serializer = PackageFeatureBulkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        wanted = set(serializer.validated_data["feature_ids"])
        with transaction.atomic():
            existing = {
                pf.feature_id: pf
                for pf in package.package_features.all()
            }
            for fid in wanted:
                pf = existing.get(fid)
                if pf is None:
                    PlatformPackageFeature.objects.create(
                        package=package, feature_id=fid, is_enabled=True
                    )
                elif not pf.is_enabled:
                    pf.is_enabled = True
                    pf.save(update_fields=["is_enabled"])
            for fid, pf in existing.items():
                if fid not in wanted and pf.is_enabled:
                    pf.is_enabled = False
                    pf.save(update_fields=["is_enabled"])
        return Response({"status": "ok", "feature_count": len(wanted)})

