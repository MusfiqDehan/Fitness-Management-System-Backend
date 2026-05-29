from rest_framework import generics, permissions, status
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response
from rest_framework.filters import SearchFilter
from rest_framework.views import APIView
from django.db.models import Q
from django.utils import timezone

from .models import (
    SiteBanner,
    PromoBanner,
    PageContent,
    BlogCategory,
    Blog,
)
from .serializers import (
    SiteBannerSerializer,
    PromoBannerSerializer,
    PageContentSerializer,
    BlogCategorySerializer,
    BlogListSerializer,
    BlogDetailSerializer,
    DashboardBlogSerializer,
)

from apps.access.permissions import HasFeatureMethodPermission


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


# -------------------------------------------------------
# Site Banner (Hero Banner) - Dashboard CRUD
# -------------------------------------------------------

class SiteBannerBaseAPIView(GenericAPIView):
    feature_key = 'cms.banners'
    queryset = SiteBanner.objects.all().order_by('position', 'created_at')
    serializer_class = SiteBannerSerializer
    permission_classes = [HasFeatureMethodPermission]
    filter_backends = [SearchFilter]
    search_fields = ['title', 'subtitle']


class SiteBannerListAPIView(ListModelAPIView, SiteBannerBaseAPIView):
    pass


class SiteBannerCreateAPIView(CreateModelAPIView, SiteBannerBaseAPIView):
    pass


class SiteBannerRetrieveAPIView(RetrieveModelAPIView, SiteBannerBaseAPIView):
    pass


class SiteBannerUpdateAPIView(UpdateModelAPIView, SiteBannerBaseAPIView):
    pass


class SiteBannerDeleteAPIView(DestroyModelAPIView, SiteBannerBaseAPIView):
    pass


# -------------------------------------------------------
# Site Banner - Public Read
# -------------------------------------------------------

class PublicSiteBannerListView(generics.ListAPIView):
    """GET /api/v1/cms/site-banners/ — active hero banners, ordered by position."""
    serializer_class = SiteBannerSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        today = timezone.now().date()
        return SiteBanner.objects.filter(is_active=True).filter(
            Q(start_date__isnull=True) | Q(start_date__lte=today)
        ).filter(
            Q(end_date__isnull=True) | Q(end_date__gte=today)
        ).order_by('position', 'created_at')


# -------------------------------------------------------
# Promo Banner (Top Bar / Popup Modal) - Dashboard CRUD
# -------------------------------------------------------

class PromoBannerBaseAPIView(GenericAPIView):
    feature_key = 'cms.banners'
    queryset = PromoBanner.objects.all().order_by('-updated_at', '-created_at')
    serializer_class = PromoBannerSerializer
    permission_classes = [HasFeatureMethodPermission]
    filter_backends = [SearchFilter]
    search_fields = ['title', 'subtitle', 'link_url', 'alt_text']


class PromoBannerListAPIView(ListModelAPIView, PromoBannerBaseAPIView):
    pass


class PromoBannerCreateAPIView(CreateModelAPIView, PromoBannerBaseAPIView):
    pass


class PromoBannerRetrieveAPIView(RetrieveModelAPIView, PromoBannerBaseAPIView):
    pass


class PromoBannerUpdateAPIView(UpdateModelAPIView, PromoBannerBaseAPIView):
    pass


class PromoBannerDeleteAPIView(DestroyModelAPIView, PromoBannerBaseAPIView):
    pass


# -------------------------------------------------------
# Promo Banner - Public Read
# -------------------------------------------------------

class PublicPromoBannerListView(generics.ListAPIView):
    """GET /api/v1/cms/promo-banners/ — active promo banners within date range."""
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


# -------------------------------------------------------
# Page Content (CMS) - Dashboard CRUD
# -------------------------------------------------------

class PageContentBaseAPIView(GenericAPIView):
    feature_key = 'cms.blogs'
    queryset = PageContent.objects.all().order_by('page_name')
    serializer_class = PageContentSerializer
    permission_classes = [HasFeatureMethodPermission]
    filter_backends = [SearchFilter]
    search_fields = ['page_name', 'title', 'subtitle']


class PageContentListAPIView(ListModelAPIView, PageContentBaseAPIView):
    pass


class PageContentCreateAPIView(CreateModelAPIView, PageContentBaseAPIView):
    pass


class PageContentRetrieveAPIView(RetrieveModelAPIView, PageContentBaseAPIView):
    pass


class PageContentUpdateAPIView(UpdateModelAPIView, PageContentBaseAPIView):
    pass


class PageContentDeleteAPIView(DestroyModelAPIView, PageContentBaseAPIView):
    pass


# -------------------------------------------------------
# Page Content - Public Read
# -------------------------------------------------------

class PublicPageContentListView(generics.ListAPIView):
    """GET /api/v1/cms/public/page-contents/ — list active page content records."""
    serializer_class = PageContentSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        return PageContent.objects.filter(is_active=True).order_by('page_name')


# -------------------------------------------------------
# Blog Category - Dashboard CRUD
# -------------------------------------------------------

class BlogCategoryBaseAPIView(GenericAPIView):
    feature_key = 'cms.blogs'
    queryset = BlogCategory.objects.order_by('id')
    serializer_class = BlogCategorySerializer
    permission_classes = [HasFeatureMethodPermission]


class BlogCategoryListAPIView(ListModelAPIView, BlogCategoryBaseAPIView):
    pass


class BlogCategoryCreateAPIView(CreateModelAPIView, BlogCategoryBaseAPIView):
    pass


class BlogCategoryRetrieveAPIView(RetrieveModelAPIView, BlogCategoryBaseAPIView):
    pass


class BlogCategoryUpdateAPIView(UpdateModelAPIView, BlogCategoryBaseAPIView):
    pass


class BlogCategoryDeleteAPIView(DestroyModelAPIView, BlogCategoryBaseAPIView):
    pass


# -------------------------------------------------------
# Blog - Dashboard CRUD
# -------------------------------------------------------

class DashboardBlogBaseAPIView(GenericAPIView):
    feature_key = 'cms.blogs'
    queryset = Blog.objects.select_related('category', 'author').order_by('-created_at')
    serializer_class = DashboardBlogSerializer
    permission_classes = [HasFeatureMethodPermission]
    filter_backends = [SearchFilter]
    filterset_fields = ['status', 'category', 'is_show_on_home_page']
    search_fields = ['title', 'slug', 'excerpt', 'description', 'category__name']

    def perform_create(self, serializer):
        return serializer.save(author=self.request.user)


class DashboardBlogListAPIView(ListModelAPIView, DashboardBlogBaseAPIView):
    pass


class DashboardBlogCreateAPIView(DashboardBlogBaseAPIView, CreateModelAPIView):
    pass


class DashboardBlogRetrieveAPIView(RetrieveModelAPIView, DashboardBlogBaseAPIView):
    pass


class DashboardBlogUpdateAPIView(UpdateModelAPIView, DashboardBlogBaseAPIView):
    pass


class DashboardBlogDeleteAPIView(DestroyModelAPIView, DashboardBlogBaseAPIView):
    pass


# -------------------------------------------------------
# Blog - Public Read
# -------------------------------------------------------

class PublicBlogListView(generics.ListAPIView):
    serializer_class = BlogListSerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [SearchFilter]
    search_fields = ['title', 'description', 'category__name']

    def get_queryset(self):
        return Blog.objects.filter(status='published').select_related(
            'category',
            'author',
        ).order_by('-published_date')


class PublicBlogDetailView(generics.RetrieveAPIView):
    serializer_class = BlogDetailSerializer
    permission_classes = [permissions.AllowAny]
    lookup_field = 'slug'

    def get_queryset(self):
        return Blog.objects.filter(status='published').select_related(
            'category',
            'author',
        )