from rest_framework import filters, status
from rest_framework.generics import GenericAPIView
from rest_framework.views import APIView
from apps.quick_action.models import (
    GymClass,
    ClassBooking,
    Category,
    Contact,
    FitHiveSupport,
    Package,
    GymClub,
    GymSchedule,
)
from apps.quick_action.serializers import (
    GymClassSerializer,
    ClassBookingSerializer,
    CategorySerializer,
    ContactDashboardSerializer,
    FitHiveSupportDashboardSerializer,
    PackageSerializer,
    GymClubSerializer,
    GymScheduleSerializer,
)
from apps.membership.serializers import (
    MemberSerializer,
    MemberPackageSerializer,
    PaymentSerializer,
    AttendanceSerializer,
)
from apps.membership.models import (
    MemberPackage,
    Member,
    Payment,
    Attendance
)
from apps.access.permissions import HasFeatureMethodPermission
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.response import Response


class ListModelAPIView(GenericAPIView):
    def get(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class UnpaginatedListModelAPIView(GenericAPIView):
    def get(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class CreateModelAPIView(GenericAPIView):
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = self.perform_create(serializer)
        return Response(self.get_serializer(instance).data, status=status.HTTP_201_CREATED)

    def perform_create(self, serializer):
        return serializer.save()


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
        updated_instance = self.perform_update(serializer)
        return Response(self.get_serializer(updated_instance).data)

    def perform_update(self, serializer):
        return serializer.save()


class DestroyModelAPIView(GenericAPIView):
    def delete(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class StatusTransitionAPIView(GenericAPIView):
    status_field = 'status'
    status_value = None
    success_message = None

    def patch(self, request, *args, **kwargs):
        instance = self.get_object()
        setattr(instance, self.status_field, self.status_value)
        instance.save(update_fields=[self.status_field])
        return Response({'message': self.success_message})


class GymClassDashboardBaseAPIView(GenericAPIView):
    feature_key = 'classes'
    queryset = GymClass.objects.prefetch_related("class_schedule").select_related(
        "category",
        "instructor",
        "instructor__instructor_profile",
    )
    serializer_class = GymClassSerializer
    permission_classes = [HasFeatureMethodPermission]

    def perform_create(self, serializer):
        return serializer.save(instructor=self.request.user)


class GymClassDashboardListAPIView(ListModelAPIView, GymClassDashboardBaseAPIView):
    pass


class GymClassDashboardCreateAPIView(GymClassDashboardBaseAPIView, CreateModelAPIView):
    pass


class GymClassDashboardRetrieveAPIView(RetrieveModelAPIView, GymClassDashboardBaseAPIView):
    pass


class GymClassDashboardUpdateAPIView(UpdateModelAPIView, GymClassDashboardBaseAPIView):
    pass


class GymClassDashboardDeleteAPIView(DestroyModelAPIView, GymClassDashboardBaseAPIView):
    pass


class GymClassLevelsAPIView(APIView):
    feature_key = 'classes'
    permission_classes = [HasFeatureMethodPermission]

    def get(self, request):
        levels = [choice[0] for choice in GymClass.LEVEL_CHOICES]
        return Response(levels)


class GymClassCategoryDashboardBaseAPIView(GenericAPIView):
    feature_key = 'classes'
    queryset = Category.objects.order_by('id')
    serializer_class = CategorySerializer
    permission_classes = [HasFeatureMethodPermission]


class GymClassCategoryDashboardListAPIView(ListModelAPIView, GymClassCategoryDashboardBaseAPIView):
    pass


class GymClassCategoryDashboardCreateAPIView(CreateModelAPIView, GymClassCategoryDashboardBaseAPIView):
    pass


class GymClassCategoryDashboardRetrieveAPIView(RetrieveModelAPIView, GymClassCategoryDashboardBaseAPIView):
    pass


class GymClassCategoryDashboardUpdateAPIView(UpdateModelAPIView, GymClassCategoryDashboardBaseAPIView):
    pass


class GymClassCategoryDashboardDeleteAPIView(DestroyModelAPIView, GymClassCategoryDashboardBaseAPIView):
    pass


class ClassBookingBaseAPIView(GenericAPIView):
    feature_key = 'classes.bookings'
    serializer_class = ClassBookingSerializer
    permission_classes = [HasFeatureMethodPermission]

    def get_queryset(self):
        user = self.request.user

        if user.is_staff or user.is_superuser:
            return ClassBooking.objects.select_related(
                "user",
                "user__student_profile",
                "gym_class",
                "gym_class__instructor",
                "gym_class__instructor__instructor_profile",
                "selected_schedule",
            ).prefetch_related("gym_class__class_schedule")

        return ClassBooking.objects.filter(
            user=user
        ).select_related(
            "user",
            "user__student_profile",
            "gym_class",
            "gym_class__instructor",
            "gym_class__instructor__instructor_profile",
            "selected_schedule",
        ).prefetch_related("gym_class__class_schedule")

    def perform_create(self, serializer):
        return serializer.save(user=self.request.user)


class ClassBookingListAPIView(ListModelAPIView, ClassBookingBaseAPIView):
    pass


class ClassBookingCreateAPIView(ClassBookingBaseAPIView, CreateModelAPIView):
    pass


class ClassBookingRetrieveAPIView(RetrieveModelAPIView, ClassBookingBaseAPIView):
    pass


class ClassBookingUpdateAPIView(UpdateModelAPIView, ClassBookingBaseAPIView):
    pass


class ClassBookingDeleteAPIView(DestroyModelAPIView, ClassBookingBaseAPIView):
    pass


# Contact
class DashboardContactBaseAPIView(GenericAPIView):
    feature_key = 'crm.contacts'
    queryset = Contact.objects.all().order_by("-created_at")
    serializer_class = ContactDashboardSerializer
    permission_classes = [HasFeatureMethodPermission]

    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]

    filterset_fields = ["status", "preferred_club"]

    search_fields = [
        "name",
        "email",
        "phone",
        "subject",
        "message",
    ]

    ordering_fields = ["created_at", "name", "status"]
    ordering = ["-created_at"]

    def get_queryset(self):
        queryset = super().get_queryset()
        status_param = self.request.query_params.get("status")
        if status_param:
            queryset = queryset.filter(status=status_param)
        return queryset


class DashboardContactListAPIView(ListModelAPIView, DashboardContactBaseAPIView):
    pass


class DashboardContactCreateAPIView(CreateModelAPIView, DashboardContactBaseAPIView):
    pass


class DashboardContactRetrieveAPIView(RetrieveModelAPIView, DashboardContactBaseAPIView):
    pass


class DashboardContactUpdateAPIView(UpdateModelAPIView, DashboardContactBaseAPIView):
    pass


class DashboardContactDeleteAPIView(DestroyModelAPIView, DashboardContactBaseAPIView):
    pass


class DashboardContactMarkAsReadAPIView(StatusTransitionAPIView, DashboardContactBaseAPIView):
    status_value = Contact.STATUS_READ
    success_message = 'Marked as read'


class DashboardContactMarkAsRespondedAPIView(StatusTransitionAPIView, DashboardContactBaseAPIView):
    status_value = Contact.STATUS_RESPONDED
    success_message = 'Marked as responded'


class DashboardContactNewListAPIView(UnpaginatedListModelAPIView, DashboardContactBaseAPIView):
    def get_queryset(self):
        return Contact.objects.filter(status=Contact.STATUS_NEW).order_by('-created_at')


class DashboardContactReadListAPIView(UnpaginatedListModelAPIView, DashboardContactBaseAPIView):
    def get_queryset(self):
        return Contact.objects.filter(status=Contact.STATUS_READ).order_by('-created_at')


class DashboardContactRespondedListAPIView(UnpaginatedListModelAPIView, DashboardContactBaseAPIView):
    def get_queryset(self):
        return Contact.objects.filter(status=Contact.STATUS_RESPONDED).order_by('-created_at')


# Fithive Support
class DashboardFitHiveSupportBaseAPIView(GenericAPIView):
    feature_key = 'crm.inquiries'
    queryset = FitHiveSupport.objects.all().order_by("-created_at")
    serializer_class = FitHiveSupportDashboardSerializer
    permission_classes = [HasFeatureMethodPermission]

    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]

    filterset_fields = ["status", "interested_in"]

    search_fields = [
        "name",
        "email",
        "phone",
        "interested_in",
    ]

    ordering_fields = ["created_at", "name", "status"]
    ordering = ["-created_at"]


class DashboardFitHiveSupportListAPIView(ListModelAPIView, DashboardFitHiveSupportBaseAPIView):
    pass


class DashboardFitHiveSupportCreateAPIView(CreateModelAPIView, DashboardFitHiveSupportBaseAPIView):
    pass


class DashboardFitHiveSupportRetrieveAPIView(RetrieveModelAPIView, DashboardFitHiveSupportBaseAPIView):
    pass


class DashboardFitHiveSupportUpdateAPIView(UpdateModelAPIView, DashboardFitHiveSupportBaseAPIView):
    pass


class DashboardFitHiveSupportDeleteAPIView(DestroyModelAPIView, DashboardFitHiveSupportBaseAPIView):
    pass


class DashboardFitHiveSupportMarkAsReadAPIView(StatusTransitionAPIView, DashboardFitHiveSupportBaseAPIView):
    status_value = FitHiveSupport.STATUS_READ
    success_message = 'Marked as read'


class DashboardFitHiveSupportMarkAsRespondedAPIView(StatusTransitionAPIView, DashboardFitHiveSupportBaseAPIView):
    status_value = FitHiveSupport.STATUS_RESPONDED
    success_message = 'Marked as responded'


# Package
class PackageDashboardBaseAPIView(GenericAPIView):
    feature_key = 'members.packages'
    queryset = Package.objects.all().order_by('display_order', 'name')
    serializer_class = PackageSerializer
    permission_classes = [HasFeatureMethodPermission]


class PackageListAPIView(ListModelAPIView, PackageDashboardBaseAPIView):
    pass


class PackageCreateAPIView(CreateModelAPIView, PackageDashboardBaseAPIView):
    pass


class PackageRetrieveAPIView(RetrieveModelAPIView, PackageDashboardBaseAPIView):
    pass


class PackageUpdateAPIView(UpdateModelAPIView, PackageDashboardBaseAPIView):
    pass


class PackageDeleteAPIView(DestroyModelAPIView, PackageDashboardBaseAPIView):
    pass


# Gym Club
class GymClubDashboardBaseAPIView(GenericAPIView):
    feature_key = 'clubs'
    queryset = GymClub.objects.prefetch_related('facilities').all()
    serializer_class = GymClubSerializer
    permission_classes = [HasFeatureMethodPermission]


class GymClubDashboardListAPIView(ListModelAPIView, GymClubDashboardBaseAPIView):
    pass


class GymClubDashboardCreateAPIView(CreateModelAPIView, GymClubDashboardBaseAPIView):
    pass


class GymClubDashboardRetrieveAPIView(RetrieveModelAPIView, GymClubDashboardBaseAPIView):
    pass


class GymClubDashboardUpdateAPIView(UpdateModelAPIView, GymClubDashboardBaseAPIView):
    pass


class GymClubDashboardDeleteAPIView(DestroyModelAPIView, GymClubDashboardBaseAPIView):
    pass


# MemberPackage
class MemberPackageDashboardBaseAPIView(GenericAPIView):
    feature_key = 'members.packages'
    queryset = MemberPackage.objects.all().order_by('name')
    serializer_class = MemberPackageSerializer
    permission_classes = [HasFeatureMethodPermission]


class PackageDashboardListAPIView(ListModelAPIView, MemberPackageDashboardBaseAPIView):
    pass


class PackageDashboardCreateAPIView(CreateModelAPIView, MemberPackageDashboardBaseAPIView):
    pass


class PackageDashboardRetrieveAPIView(RetrieveModelAPIView, MemberPackageDashboardBaseAPIView):
    pass


class PackageDashboardUpdateAPIView(UpdateModelAPIView, MemberPackageDashboardBaseAPIView):
    pass


class PackageDashboardDeleteAPIView(DestroyModelAPIView, MemberPackageDashboardBaseAPIView):
    pass


# Member
class MemberDashboardBaseAPIView(GenericAPIView):
    feature_key = 'members'
    queryset = Member.objects.select_related('member_package').all().order_by('-created_at')
    serializer_class = MemberSerializer
    permission_classes = [HasFeatureMethodPermission]

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['membership_type', 'member_package', 'is_active']
    search_fields = ['full_name', 'phone_number', 'card_id', 'fingerprint_id']
    ordering_fields = ['start_date', 'end_date', 'full_name', 'created_at']
    ordering = ['-created_at']


class MemberDashboardListAPIView(ListModelAPIView, MemberDashboardBaseAPIView):
    pass


class MemberDashboardCreateAPIView(CreateModelAPIView, MemberDashboardBaseAPIView):
    pass


class MemberDashboardRetrieveAPIView(RetrieveModelAPIView, MemberDashboardBaseAPIView):
    pass


class MemberDashboardUpdateAPIView(UpdateModelAPIView, MemberDashboardBaseAPIView):
    pass


class MemberDashboardDeleteAPIView(DestroyModelAPIView, MemberDashboardBaseAPIView):
    pass


# Payment
class PaymentDashboardBaseAPIView(GenericAPIView):
    feature_key = 'payments'
    queryset = Payment.objects.select_related('member').all().order_by('-payment_date')
    serializer_class = PaymentSerializer
    permission_classes = [HasFeatureMethodPermission]

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['payment_type', 'member']
    search_fields = ['member__full_name', 'note']
    ordering_fields = ['payment_date', 'amount', 'member__full_name']
    ordering = ['-payment_date']


class PaymentDashboardListAPIView(ListModelAPIView, PaymentDashboardBaseAPIView):
    pass


class PaymentDashboardCreateAPIView(CreateModelAPIView, PaymentDashboardBaseAPIView):
    pass


class PaymentDashboardRetrieveAPIView(RetrieveModelAPIView, PaymentDashboardBaseAPIView):
    pass


class PaymentDashboardUpdateAPIView(UpdateModelAPIView, PaymentDashboardBaseAPIView):
    pass


class PaymentDashboardDeleteAPIView(DestroyModelAPIView, PaymentDashboardBaseAPIView):
    pass


# Attendance
class AttendanceDashboardBaseAPIView(GenericAPIView):
    feature_key = 'members.attendance'
    queryset = Attendance.objects.select_related('member').all().order_by('-check_in_time')
    serializer_class = AttendanceSerializer
    permission_classes = [HasFeatureMethodPermission]

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['entry_method', 'member']
    search_fields = ['member__full_name', 'device_id']
    ordering_fields = ['check_in_time', 'check_out_time', 'member__full_name']
    ordering = ['-check_in_time']


class AttendanceDashboardListAPIView(ListModelAPIView, AttendanceDashboardBaseAPIView):
    pass


class AttendanceDashboardCreateAPIView(CreateModelAPIView, AttendanceDashboardBaseAPIView):
    pass


class AttendanceDashboardRetrieveAPIView(RetrieveModelAPIView, AttendanceDashboardBaseAPIView):
    pass


class AttendanceDashboardUpdateAPIView(UpdateModelAPIView, AttendanceDashboardBaseAPIView):
    pass


class AttendanceDashboardDeleteAPIView(DestroyModelAPIView, AttendanceDashboardBaseAPIView):
    pass


# File Upload
import os
import uuid
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.conf import settings
from rest_framework.parsers import MultiPartParser, FormParser

ALLOWED_MIME_TYPES = {
    'image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/svg+xml',
    'video/mp4', 'video/webm', 'video/ogg',
}
MAX_UPLOAD_SIZE_MB = 50


class FileUploadView(APIView):
    feature_keys = ['cms.banners', 'cms.blogs', 'clubs', 'classes']
    permission_classes = [HasFeatureMethodPermission]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        uploaded = request.FILES.get('file')
        if not uploaded:
            return Response(
                {"error": "No file provided. Send a multipart field named 'file'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if uploaded.content_type not in ALLOWED_MIME_TYPES:
            return Response(
                {"error": f"Unsupported file type '{uploaded.content_type}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        max_bytes = MAX_UPLOAD_SIZE_MB * 1024 * 1024
        if uploaded.size > max_bytes:
            return Response(
                {"error": f"File too large. Maximum allowed size is {MAX_UPLOAD_SIZE_MB} MB."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        original_ext = os.path.splitext(uploaded.name)[-1].lower()
        unique_name = f"{uuid.uuid4().hex}{original_ext}"
        save_path = os.path.join('uploads', unique_name)

        saved_name = default_storage.save(save_path, ContentFile(uploaded.read()))

        storage_url = default_storage.url(saved_name)
        if storage_url.startswith('http://') or storage_url.startswith('https://'):
            file_url = storage_url
        else:
            file_url = request.build_absolute_uri(storage_url)

        return Response({"file_url": file_url}, status=status.HTTP_201_CREATED)


# Gym Schedule
class GymScheduleDashboardBaseAPIView(GenericAPIView):
    feature_key = 'classes'
    queryset = GymSchedule.objects.all().order_by('display_order', 'day', 'time')
    serializer_class = GymScheduleSerializer
    permission_classes = [HasFeatureMethodPermission]
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ['day', 'is_active', 'difficulty_level']
    search_fields = ['class_name', 'instructor', 'location', 'category']


class GymScheduleDashboardListAPIView(ListModelAPIView, GymScheduleDashboardBaseAPIView):
    pass


class GymScheduleDashboardCreateAPIView(CreateModelAPIView, GymScheduleDashboardBaseAPIView):
    pass


class GymScheduleDashboardRetrieveAPIView(RetrieveModelAPIView, GymScheduleDashboardBaseAPIView):
    pass


class GymScheduleDashboardUpdateAPIView(UpdateModelAPIView, GymScheduleDashboardBaseAPIView):
    pass


class GymScheduleDashboardDeleteAPIView(DestroyModelAPIView, GymScheduleDashboardBaseAPIView):
    pass