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