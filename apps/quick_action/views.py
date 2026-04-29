from rest_framework import generics, permissions, status
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response
from rest_framework.filters import SearchFilter
from rest_framework.views import APIView
from django.db.models import Q
from django.utils import timezone
from .models import(
    Banner,
    GymClub,
    GymClass,
    Category,
    ClassSchedule,
    GymSchedule,
    Blog,
    BlogCategory,
    Contact,
    FitHiveSupport,
    Package,
    SiteBanner,
    PromoBanner,
    SiteSettings,
    PageContent,
)
from .serializers import (
    BannerSerializer,
    GymClubSerializer,
    GymClassSerializer,
    ClassBookingSerializer,
    CategorySerializer,
    ClassScheduleSerializer,
    GymScheduleSerializer,
    BlogListSerializer,
    BlogDetailSerializer,
    BlogCategorySerializer,
    ContactCreateSerializer,
    FitHiveSupportCreateSerializer,
    PackageSerializer,
    SiteBannerSerializer,
    PromoBannerSerializer,
    SiteSettingsSerializer,
    PageContentSerializer,
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


class BannerListAPIView(ListModelAPIView):
    queryset = Banner.objects.filter(is_active=True).order_by('-created_at', '-id')
    serializer_class = BannerSerializer


class BannerCreateAPIView(CreateModelAPIView):
    queryset = Banner.objects.filter(is_active=True).order_by('-created_at', '-id')
    serializer_class = BannerSerializer


class BannerRetrieveAPIView(RetrieveModelAPIView):
    queryset = Banner.objects.filter(is_active=True).order_by('-created_at', '-id')
    serializer_class = BannerSerializer


class BannerUpdateAPIView(UpdateModelAPIView):
    queryset = Banner.objects.filter(is_active=True).order_by('-created_at', '-id')
    serializer_class = BannerSerializer


class BannerDeleteAPIView(DestroyModelAPIView):
    queryset = Banner.objects.filter(is_active=True).order_by('-created_at', '-id')
    serializer_class = BannerSerializer


class GymClubListAPIView(ListModelAPIView):
    queryset = GymClub.objects.prefetch_related('facilities').all()
    serializer_class = GymClubSerializer


class GymClubCreateAPIView(CreateModelAPIView):
    queryset = GymClub.objects.prefetch_related('facilities').all()
    serializer_class = GymClubSerializer


class GymClubRetrieveAPIView(RetrieveModelAPIView):
    queryset = GymClub.objects.prefetch_related('facilities').all()
    serializer_class = GymClubSerializer


class GymClubUpdateAPIView(UpdateModelAPIView):
    queryset = GymClub.objects.prefetch_related('facilities').all()
    serializer_class = GymClubSerializer


class GymClubDeleteAPIView(DestroyModelAPIView):
    queryset = GymClub.objects.prefetch_related('facilities').all()
    serializer_class = GymClubSerializer

class CategoryListCreateView(generics.ListCreateAPIView):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer


class ScheduleListCreateView(generics.ListCreateAPIView):
    queryset = ClassSchedule.objects.all()
    serializer_class = ClassScheduleSerializer

# gym class

class GymClassListCreateView(generics.ListCreateAPIView):
    queryset = GymClass.objects.prefetch_related("class_schedule").select_related(
        "category",
        "instructor",
        "instructor__instructor_profile",
    ).order_by('-created_at', '-id')
    serializer_class = GymClassSerializer


class GymClassDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = GymClass.objects.prefetch_related("class_schedule").select_related(
        "category",
        "instructor",
        "instructor__instructor_profile",
    ).order_by('-created_at', '-id')
    serializer_class = GymClassSerializer

# Blog views
class PublicBlogListView(generics.ListAPIView):
    serializer_class = BlogListSerializer
    filter_backends = [SearchFilter]
    search_fields = ['title', 'description', 'category__name']

    def get_queryset(self):
        return Blog.objects.filter(status='published').select_related(
            'category',
            'author',
        ).order_by('-published_date')

class PublicBlogDetailView(generics.RetrieveAPIView):
    serializer_class = BlogDetailSerializer
    lookup_field = 'slug'

    def get_queryset(self):
        return Blog.objects.filter(status='published').select_related(
            'category',
            'author',
        )

class BlogCategoryListAPIView(ListModelAPIView):
    queryset = BlogCategory.objects.order_by('id')
    serializer_class = BlogCategorySerializer


class BlogCategoryCreateAPIView(CreateModelAPIView):
    queryset = BlogCategory.objects.order_by('id')
    serializer_class = BlogCategorySerializer


class BlogCategoryRetrieveAPIView(RetrieveModelAPIView):
    queryset = BlogCategory.objects.order_by('id')
    serializer_class = BlogCategorySerializer


class BlogCategoryUpdateAPIView(UpdateModelAPIView):
    queryset = BlogCategory.objects.order_by('id')
    serializer_class = BlogCategorySerializer


class BlogCategoryDeleteAPIView(DestroyModelAPIView):
    queryset = BlogCategory.objects.order_by('id')
    serializer_class = BlogCategorySerializer


# Contact 
class ContactCreateAPIView(generics.CreateAPIView):
    queryset = Contact.objects.all()
    serializer_class = ContactCreateSerializer
    
# Fithive support
class FitHiveSupportCreateAPIView(generics.CreateAPIView):
    queryset = FitHiveSupport.objects.all()
    serializer_class = FitHiveSupportCreateSerializer
   
# package
class PublicPackageListAPIView(ListModelAPIView):
    queryset = Package.objects.filter(is_active=True).prefetch_related(
        'features',
        'addons',
    ).order_by('display_order', 'name')
    serializer_class = PackageSerializer
    permission_classes = [permissions.AllowAny]  # Public endpoint


class PublicPackageRetrieveAPIView(RetrieveModelAPIView):
    queryset = Package.objects.filter(is_active=True).prefetch_related(
        'features',
        'addons',
    ).order_by('display_order', 'name')
    serializer_class = PackageSerializer
    permission_classes = [permissions.AllowAny]


# -------------------------------------------------------
# Public (no-auth) read-only views
# -------------------------------------------------------

class PublicSiteBannerListView(generics.ListAPIView):
    """GET /api/site-banners/ — active hero banners, ordered by position."""
    serializer_class = SiteBannerSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        return SiteBanner.objects.filter(is_active=True).order_by('position', 'created_at')


class PublicPromoBannerListView(generics.ListAPIView):
    """GET /api/promo-banners/?banner_type=top_bar — active promo banners within date range."""
    serializer_class = PromoBannerSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        today = timezone.now().date()
        qs = PromoBanner.objects.filter(is_active=True)
        banner_type = self.request.query_params.get('banner_type')
        if banner_type:
            qs = qs.filter(banner_type=banner_type)
        qs = qs.filter(
            Q(start_date__isnull=True) | Q(start_date__lte=today)
        ).filter(
            Q(end_date__isnull=True) | Q(end_date__gte=today)
        )
        return qs


class PublicSiteSettingsView(APIView):
    """GET /api/site-settings/ — public singleton site settings (logo, nav, footer)."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        settings_obj = SiteSettings.objects.first()
        if not settings_obj:
            return Response(status=status.HTTP_204_NO_CONTENT)
        serializer = SiteSettingsSerializer(settings_obj)
        return Response(serializer.data)


class PublicPageContentListView(generics.ListAPIView):
    """GET /api/page-contents/ — list active page content records (page_name + title only)."""
    serializer_class = PageContentSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        return PageContent.objects.filter(is_active=True).order_by('page_name')


class PublicGymScheduleListView(generics.ListAPIView):
    """GET /api/gym-schedules/ — active gym schedules for the homepage."""
    serializer_class = GymScheduleSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        return GymSchedule.objects.filter(is_active=True).order_by('display_order', 'day', 'time')