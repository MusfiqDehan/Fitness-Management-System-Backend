from rest_framework.viewsets import ModelViewSet
from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import generics, status
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

class BannerViewSet(ModelViewSet):
    queryset = Banner.objects.filter(is_active=True).order_by('-created_at', '-id')
    serializer_class = BannerSerializer

class GymClubViewSet(ModelViewSet):
    queryset = GymClub.objects.all()
    serializer_class = GymClubSerializer

class CategoryListCreateView(generics.ListCreateAPIView):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer


class ScheduleListCreateView(generics.ListCreateAPIView):
    queryset = ClassSchedule.objects.all()
    serializer_class = ClassScheduleSerializer

# gym class

class GymClassListCreateView(generics.ListCreateAPIView):
    queryset = GymClass.objects.prefetch_related("class_schedule").select_related("category").order_by('-created_at', '-id')
    serializer_class = GymClassSerializer


class GymClassDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = GymClass.objects.prefetch_related("class_schedule").select_related("category").order_by('-created_at', '-id')
    serializer_class = GymClassSerializer

# Blog views
class PublicBlogListView(generics.ListAPIView):
    serializer_class = BlogListSerializer
    filter_backends = [SearchFilter]
    search_fields = ['title', 'description', 'category__name']

    def get_queryset(self):
        return Blog.objects.filter(status='published').order_by('-published_date')

class PublicBlogDetailView(generics.RetrieveAPIView):
    serializer_class = BlogDetailSerializer
    lookup_field = 'slug'

    def get_queryset(self):
        return Blog.objects.filter(status='published')

class BlogCategoryViewSet(ModelViewSet):
    queryset = BlogCategory.objects.all()
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
class PublicPackageViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Package.objects.filter(is_active=True).order_by('display_order', 'name')
    serializer_class = PackageSerializer
    permission_classes = [permissions.AllowAny]  # Public endpoint


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