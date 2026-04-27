from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from main_app.models import (
    Blog, 
    BlogCategory, 
    GymClass,
    ClassBooking,
    Category,
    Contact,
    FitHiveSupport,
    Package,
    GymClub,
    SiteBanner,
    PromoBanner,
    SiteSettings,
    PageContent,
    GymSchedule,
)
from main_app.serializers import (
    BlogDetailSerializer, 
    BlogCategorySerializer, 
    DashboardBlogSerializer, 
    GymClassSerializer,
    ClassBookingSerializer,
    CategorySerializer,
    ContactDashboardSerializer,
    FitHiveSupportDashboardSerializer,
    PackageSerializer,
    GymClubSerializer,
    SiteBannerSerializer,
    PromoBannerSerializer,
    SiteSettingsSerializer,
    PageContentSerializer,
    GymScheduleSerializer,
)
from membership_management.serializers import (
    MemberSerializer,
    MemberPackageSerializer,
    PaymentSerializer,
    AttendanceSerializer,
)
from membership_management.models import (
    MemberPackage,
    Member,
    Payment, 
    Attendance
)
from .permissions import IsAdminStaffOrSuperuser
from rest_framework.filters import SearchFilter,OrderingFilter
from rest_framework import filters
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.decorators import action
from rest_framework.response import Response


class DashboardBlogViewSet(ModelViewSet):
    queryset = Blog.objects.all().order_by('-created_at')
    serializer_class = DashboardBlogSerializer
    permission_classes = [IsAdminStaffOrSuperuser]
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ['status', 'category']
    search_fields = ['title', 'description']

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)

class DashboardBlogCategoryViewSet(ModelViewSet):
    queryset = BlogCategory.objects.all()
    serializer_class = BlogCategorySerializer
    permission_classes = [IsAdminStaffOrSuperuser]


# class

class GymClassDashboardViewSet(ModelViewSet):
    queryset = GymClass.objects.prefetch_related("class_schedule").select_related("category")
    serializer_class = GymClassSerializer
    permission_classes = [IsAdminStaffOrSuperuser]  # only logged in users

    def perform_create(self, serializer):
        serializer.save(instructor=self.request.user)

    @action(detail=False, methods=['get'])
    def levels(self, request):
        levels = [choice[0] for choice in GymClass.LEVEL_CHOICES]
        return Response(levels)


class GymClassCategoryDashboardViewSet(ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [IsAdminStaffOrSuperuser]

class ClassBookingViewSet(ModelViewSet):
    serializer_class = ClassBookingSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user

        if user.is_staff or user.is_superuser:
            return ClassBooking.objects.select_related(
                "user", "gym_class"
            ).prefetch_related("gym_class__class_schedule")

        return ClassBooking.objects.filter(
            user=user
        ).select_related(
            "gym_class"
        ).prefetch_related("gym_class__class_schedule")

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

# Conatct
class DashboardContactViewSet(ModelViewSet):
    queryset = Contact.objects.all().order_by("-created_at")
    serializer_class = ContactDashboardSerializer
    permission_classes = [IsAdminStaffOrSuperuser]

    # ADD THIS
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]

    # Exact filter
    filterset_fields = ["status", "preferred_club"]

    # Search fields
    search_fields = [
        "name",
        "email",
        "phone",
        "subject",
        "message",
    ]

    # Ordering
    ordering_fields = ["created_at", "name", "status"]
    ordering = ["-created_at"]

    # Filter by status using query param
    def get_queryset(self):
        queryset = super().get_queryset()
        status_param = self.request.query_params.get("status")
        if status_param:
            queryset = queryset.filter(status=status_param)
        return queryset

    # Mark as Read
    @action(detail=True, methods=["patch"])
    def mark_as_read(self, request, pk=None):
        contact = self.get_object()
        contact.status = Contact.STATUS_READ
        contact.save()
        return Response({"message": "Marked as read"})

    # Mark as Responded
    @action(detail=True, methods=["patch"])
    def mark_as_responded(self, request, pk=None):
        contact = self.get_object()
        contact.status = Contact.STATUS_RESPONDED
        contact.save()
        return Response({"message": "Marked as responded"})

    # Custom list routes for status
    @action(detail=False, methods=["get"])
    def new(self, request):
        contacts = Contact.objects.filter(status=Contact.STATUS_NEW)
        serializer = self.get_serializer(contacts, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def read(self, request):
        contacts = Contact.objects.filter(status=Contact.STATUS_READ)
        serializer = self.get_serializer(contacts, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def responded(self, request):
        contacts = Contact.objects.filter(status=Contact.STATUS_RESPONDED)
        serializer = self.get_serializer(contacts, many=True)
        return Response(serializer.data)


# -- Fithive Support --
class DashboardFitHiveSupportViewSet(ModelViewSet):
    queryset = FitHiveSupport.objects.all().order_by("-created_at")
    serializer_class = FitHiveSupportDashboardSerializer
    permission_classes = [IsAdminStaffOrSuperuser]

    # Add filtering + search
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]

    # Exact filtering
    filterset_fields = ["status", "interested_in"]

    # Search support
    search_fields = [
        "name",
        "email",
        "phone",
        "interested_in",
    ]

    # Ordering
    ordering_fields = ["created_at", "name", "status"]
    ordering = ["-created_at"]

    #  Mark as Read
    @action(detail=True, methods=["patch"])
    def mark_as_read(self, request, pk=None):
        support = self.get_object()
        support.status = FitHiveSupport.STATUS_READ
        support.save()
        return Response({"message": "Marked as read"})

    #  Mark as Responded
    @action(detail=True, methods=["patch"])
    def mark_as_responded(self, request, pk=None):
        support = self.get_object()
        support.status = FitHiveSupport.STATUS_RESPONDED
        support.save()
        return Response({"message": "Marked as responded"})


# Dashboard (CRUD for package)
class PackageViewSet(ModelViewSet):
    queryset = Package.objects.all().order_by('display_order', 'name')
    serializer_class = PackageSerializer
    permission_classes = [IsAdminStaffOrSuperuser]

# Dashboard (CRUD for gym club)
class GymClubDashboardViewSet(ModelViewSet):
    queryset = GymClub.objects.all()
    serializer_class = GymClubSerializer
    permission_classes = [IsAuthenticated, IsAdminStaffOrSuperuser]

# ----------------------------
# MemberPackage Dashboard CRUD
# ----------------------------
class PackageDashboardViewSet(ModelViewSet):
    queryset = MemberPackage.objects.all().order_by('name')
    serializer_class = MemberPackageSerializer
    permission_classes = [IsAdminStaffOrSuperuser]


# ----------------------------
# Member Dashboard CRUD
# ----------------------------
class MemberDashboardViewSet(ModelViewSet):
    queryset = Member.objects.select_related('member_package').all().order_by('-created_at')
    serializer_class = MemberSerializer
    permission_classes = [IsAdminStaffOrSuperuser]
    
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['membership_type', 'member_package', 'is_active']
    search_fields = ['full_name', 'phone_number', 'card_id', 'fingerprint_id']
    ordering_fields = ['start_date', 'end_date', 'full_name', 'created_at']
    ordering = ['-created_at']


# ----------------------------
# Payment Dashboard CRUD
# ----------------------------
class PaymentDashboardViewSet(ModelViewSet):
    queryset = Payment.objects.select_related('member').all().order_by('-payment_date')
    serializer_class = PaymentSerializer
    permission_classes = [IsAdminStaffOrSuperuser]
    
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['payment_type', 'member']
    search_fields = ['member__full_name', 'note']
    ordering_fields = ['payment_date', 'amount', 'member__full_name']
    ordering = ['-payment_date']


# ----------------------------
# Attendance Dashboard CRUD
# ----------------------------
class AttendanceDashboardViewSet(ModelViewSet):
    queryset = Attendance.objects.select_related('member').all().order_by('-check_in_time')
    serializer_class = AttendanceSerializer
    permission_classes = [IsAdminStaffOrSuperuser]
    
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['entry_method', 'member']
    search_fields = ['member__full_name', 'device_id']
    ordering_fields = ['check_in_time', 'check_out_time', 'member__full_name']
    ordering = ['-check_in_time']


# -------------------------------------------------------
# File Upload
# -------------------------------------------------------

import os
import uuid
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.conf import settings
from rest_framework.parsers import MultiPartParser, FormParser

ALLOWED_MIME_TYPES = {
    # Images
    'image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/svg+xml',
    # Videos
    'video/mp4', 'video/webm', 'video/ogg',
}
MAX_UPLOAD_SIZE_MB = 50


class FileUploadView(APIView):
    """
    POST /api/dashboard/upload/

    Accepts a single file via multipart/form-data (field name: ``file``).
    Validates MIME type (images and common web video formats) and file size
    (max 50 MB). Saves the file under MEDIA_ROOT/uploads/ with a UUID-based
    name to prevent collisions. Returns the publicly accessible URL.

    Permission: admin/staff only.
    """

    permission_classes = [IsAdminStaffOrSuperuser]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        """
        Handle file upload and return the resulting media URL.

        Expected form field: ``file``
        Returns: ``{ "file_url": "<absolute URL>" }``
        """
        from rest_framework.response import Response
        from rest_framework import status

        uploaded = request.FILES.get('file')
        if not uploaded:
            return Response(
                {"error": "No file provided. Send a multipart field named 'file'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # --- MIME type validation ---
        if uploaded.content_type not in ALLOWED_MIME_TYPES:
            return Response(
                {
                    "error": (
                        f"Unsupported file type '{uploaded.content_type}'. "
                        "Allowed: images (jpeg, png, gif, webp, svg) and "
                        "videos (mp4, webm, ogg)."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # --- File size validation ---
        max_bytes = MAX_UPLOAD_SIZE_MB * 1024 * 1024
        if uploaded.size > max_bytes:
            return Response(
                {"error": f"File too large. Maximum allowed size is {MAX_UPLOAD_SIZE_MB} MB."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # --- Generate a unique filename preserving the original extension ---
        original_ext = os.path.splitext(uploaded.name)[-1].lower()
        unique_name = f"{uuid.uuid4().hex}{original_ext}"
        save_path = os.path.join('uploads', unique_name)

        # --- Persist file ---
        saved_name = default_storage.save(save_path, ContentFile(uploaded.read()))

        # --- Build URL ---
        # default_storage.url() returns the Cloudinary CDN URL in production
        # and a relative /media/... path locally. Build absolute for local only.
        storage_url = default_storage.url(saved_name)
        if storage_url.startswith('http://') or storage_url.startswith('https://'):
            # Cloudinary (or any remote storage) already returns a full URL
            file_url = storage_url
        else:
            file_url = request.build_absolute_uri(storage_url)

        return Response({"file_url": file_url}, status=status.HTTP_201_CREATED)


# -------------------------------------------------------
# Site Banner (Hero Banner)
# -------------------------------------------------------

class SiteBannerViewSet(ModelViewSet):
    """
    CRUD ViewSet for SiteBanner (hero / slider banners).

    Endpoints (all under /api/dashboard/site-banners/):
      GET    /            – list all banners ordered by position
      POST   /            – create a new banner
      GET    /{id}/       – retrieve a single banner
      PUT    /{id}/       – full update
      PATCH  /{id}/       – partial update (e.g. toggle is_active, reorder)
      DELETE /{id}/       – delete

    Permission: admin/staff only.
    """

    queryset = SiteBanner.objects.all().order_by('position', 'created_at')
    serializer_class = SiteBannerSerializer
    permission_classes = [IsAdminStaffOrSuperuser]
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ['is_active', 'media_type']
    search_fields = ['title', 'subtitle']


# -------------------------------------------------------
# Promo Banner (Top Bar / Popup Modal)
# -------------------------------------------------------

class PromoBannerViewSet(ModelViewSet):
    """
    CRUD ViewSet for PromoBanner.

    Banners are grouped by `banner_type` on the frontend:
      - ``top_bar``     – shown as a sticky announcement bar
      - ``popup_modal`` – shown as a full-screen or centred overlay

    Endpoints (all under /api/dashboard/promo-banners/):
      GET    /            – list all promo banners
      POST   /            – create a new promo banner
      GET    /{id}/       – retrieve a single promo banner
      PUT    /{id}/       – full update
      PATCH  /{id}/       – partial update
      DELETE /{id}/       – delete

    Permission: admin/staff only.
    """

    queryset = PromoBanner.objects.all().order_by('-created_at')
    serializer_class = PromoBannerSerializer
    permission_classes = [IsAdminStaffOrSuperuser]
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ['banner_type', 'is_active']
    search_fields = ['link_url']


# -------------------------------------------------------
# Site Settings (Singleton)
# -------------------------------------------------------

class SiteSettingsAPIView(APIView):
    """
    Manage the single SiteSettings record.

    GET  /api/dashboard/site-settings/
        Returns the settings object if it exists, or HTTP 204 No Content.

    POST /api/dashboard/site-settings/
        Creates the record on first call; updates it on subsequent calls
        (upsert / get_or_create pattern). All fields are optional on update.

    Permission: admin/staff only.
    """

    permission_classes = [IsAdminStaffOrSuperuser]

    def get(self, request):
        """
        Return the current site settings, or 204 if none have been saved yet.
        """
        from rest_framework.response import Response
        from rest_framework import status

        instance = SiteSettings.objects.first()
        if instance is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        serializer = SiteSettingsSerializer(instance)
        return Response(serializer.data)

    def post(self, request):
        """
        Create or update the singleton site settings record.

        Uses get_or_create so a second POST updates rather than duplicates.
        """
        from rest_framework.response import Response
        from rest_framework import status

        instance, _ = SiteSettings.objects.get_or_create(pk=1)
        serializer = SiteSettingsSerializer(instance, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# -------------------------------------------------------
# Page Content (CMS)
# -------------------------------------------------------

class PageContentViewSet(ModelViewSet):
    """
    CRUD ViewSet for PageContent.

    Each record maps to a named site page (e.g. 'Home', 'About').
    `page_name` is unique – the serializer enforces this including during
    partial updates.

    Endpoints (all under /api/dashboard/page-content/):
      GET    /            – list all page content records
      POST   /            – create content for a new page
      GET    /{id}/       – retrieve a single page content record
      PUT    /{id}/       – full update
      PATCH  /{id}/       – partial update (e.g. toggle is_active)
      DELETE /{id}/       – delete

    Permission: admin/staff only.
    """

    queryset = PageContent.objects.all().order_by('page_name')
    serializer_class = PageContentSerializer
    permission_classes = [IsAdminStaffOrSuperuser]
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ['page_name', 'is_active']
    search_fields = ['page_name', 'title', 'subtitle']
    ordering = ['-check_in_time']


# -------------------------------------------------------
# Gym Schedule (Class Schedule Manager)
# -------------------------------------------------------

class GymScheduleDashboardViewSet(ModelViewSet):
    """
    CRUD ViewSet for GymSchedule — admin-managed class/session schedules
    that are displayed dynamically on the homepage ScheduleSection.

    Endpoints (all under /api/dashboard/gym-schedules/):
      GET    /            – list all schedules
      POST   /            – create a new schedule entry
      GET    /{id}/       – retrieve a single entry
      PUT    /{id}/       – full update
      PATCH  /{id}/       – partial update (e.g. toggle is_active)
      DELETE /{id}/       – delete

    Permission: admin/staff only.
    """

    queryset = GymSchedule.objects.all().order_by('display_order', 'day', 'time')
    serializer_class = GymScheduleSerializer
    permission_classes = [IsAdminStaffOrSuperuser]
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ['day', 'is_active', 'difficulty_level']
    search_fields = ['class_name', 'instructor', 'location', 'category']