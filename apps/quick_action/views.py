from rest_framework import generics, permissions, status
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response
from rest_framework.filters import SearchFilter
from apps.access.permissions import HasFeatureMethodPermission
from .models import (
    GymClub,
    GymClass,
    Category,
    ClassSchedule,
    GymSchedule,
    Contact,
    FitHiveSupport,
    Package,
)
from .serializers import (
    GymClubSerializer,
    GymClassSerializer,
    ClassBookingSerializer,
    CategorySerializer,
    ClassScheduleSerializer,
    GymScheduleSerializer,
    ContactCreateSerializer,
    FitHiveSupportCreateSerializer,
    PackageSerializer,
)


class ListModelAPIView(GenericAPIView):
    def get(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class CreateModelAPIView(GenericAPIView):
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        return Response(self.get_serializer(instance).data, status=status.HTTP_201_CREATED)


class RetrieveModelAPIView(GenericAPIView):
    def get(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_object())
        return Response(serializer.data)


class UpdateModelAPIView(GenericAPIView):
    def put(self, request, *args, **kwargs):
        return self._update(request, partial=False)

    def patch(self, request, *args, **kwargs):
        return self._update(request, partial=True)

    def _update(self, request, partial):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        updated_instance = serializer.save()
        return Response(self.get_serializer(updated_instance).data)


class DestroyModelAPIView(GenericAPIView):
    def delete(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class GymClubListAPIView(ListModelAPIView):
    feature_key = 'clubs'
    queryset = GymClub.objects.prefetch_related('facilities').all()
    serializer_class = GymClubSerializer
    permission_classes = [HasFeatureMethodPermission]


class GymClubCreateAPIView(CreateModelAPIView):
    feature_key = 'clubs'
    queryset = GymClub.objects.prefetch_related('facilities').all()
    serializer_class = GymClubSerializer
    permission_classes = [HasFeatureMethodPermission]


class GymClubRetrieveAPIView(RetrieveModelAPIView):
    feature_key = 'clubs'
    queryset = GymClub.objects.prefetch_related('facilities').all()
    serializer_class = GymClubSerializer
    permission_classes = [HasFeatureMethodPermission]


class GymClubUpdateAPIView(UpdateModelAPIView):
    feature_key = 'clubs'
    queryset = GymClub.objects.prefetch_related('facilities').all()
    serializer_class = GymClubSerializer
    permission_classes = [HasFeatureMethodPermission]


class GymClubDeleteAPIView(DestroyModelAPIView):
    feature_key = 'clubs'
    queryset = GymClub.objects.prefetch_related('facilities').all()
    serializer_class = GymClubSerializer
    permission_classes = [HasFeatureMethodPermission]


class CategoryListCreateView(generics.ListCreateAPIView):
    feature_key = 'classes'
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [HasFeatureMethodPermission]


class ScheduleListCreateView(generics.ListCreateAPIView):
    feature_key = 'classes'
    queryset = ClassSchedule.objects.all()
    serializer_class = ClassScheduleSerializer
    permission_classes = [HasFeatureMethodPermission]


# gym class
class GymClassListCreateView(generics.ListCreateAPIView):
    feature_key = 'classes'
    queryset = GymClass.objects.prefetch_related("class_schedule").select_related(
        "category",
        "instructor",
        "instructor__instructor_profile",
    ).order_by('-created_at', '-id')
    serializer_class = GymClassSerializer
    permission_classes = [HasFeatureMethodPermission]


class GymClassDetailView(generics.RetrieveUpdateDestroyAPIView):
    feature_key = 'classes'
    queryset = GymClass.objects.prefetch_related("class_schedule").select_related(
        "category",
        "instructor",
        "instructor__instructor_profile",
    ).order_by('-created_at', '-id')
    serializer_class = GymClassSerializer
    permission_classes = [HasFeatureMethodPermission]


# Contact
class ContactCreateAPIView(generics.CreateAPIView):
    queryset = Contact.objects.all()
    serializer_class = ContactCreateSerializer
    permission_classes = [permissions.AllowAny]


# Fithive support
class FitHiveSupportCreateAPIView(generics.CreateAPIView):
    queryset = FitHiveSupport.objects.all()
    serializer_class = FitHiveSupportCreateSerializer
    permission_classes = [permissions.AllowAny]


# package
class PublicPackageListAPIView(ListModelAPIView):
    queryset = Package.objects.filter(is_active=True).prefetch_related(
        'features',
        'addons',
    ).order_by('display_order', 'name')
    serializer_class = PackageSerializer
    permission_classes = [permissions.AllowAny]


class PublicPackageRetrieveAPIView(RetrieveModelAPIView):
    queryset = Package.objects.filter(is_active=True).prefetch_related(
        'features',
        'addons',
    ).order_by('display_order', 'name')
    serializer_class = PackageSerializer
    permission_classes = [permissions.AllowAny]


# Gym Schedule
class PublicGymScheduleListView(generics.ListAPIView):
    """GET /api/gym-schedules/ — active gym schedules for the homepage."""
    serializer_class = GymScheduleSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        return GymSchedule.objects.filter(is_active=True).order_by('display_order', 'day', 'time')