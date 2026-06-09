from django.urls import path
from .views import (
    SiteBannerListAPIView,
    SiteBannerCreateAPIView,
    SiteBannerRetrieveAPIView,
    SiteBannerUpdateAPIView,
    SiteBannerDeleteAPIView,
    PublicSiteBannerListView,
    PromoBannerListAPIView,
    PromoBannerCreateAPIView,
    PromoBannerRetrieveAPIView,
    PromoBannerUpdateAPIView,
    PromoBannerDeleteAPIView,
    PublicPromoBannerListView,
    PageContentListAPIView,
    PageContentCreateAPIView,
    PageContentRetrieveAPIView,
    PageContentUpdateAPIView,
    PageContentDeleteAPIView,
    PublicPageContentListView,
    BlogCategoryListAPIView,
    BlogCategoryCreateAPIView,
    BlogCategoryRetrieveAPIView,
    BlogCategoryUpdateAPIView,
    BlogCategoryDeleteAPIView,
    DashboardBlogListAPIView,
    DashboardBlogCreateAPIView,
    DashboardBlogRetrieveAPIView,
    DashboardBlogUpdateAPIView,
    DashboardBlogDeleteAPIView,
    PublicBlogListView,
    PublicBlogDetailView,
)

app_name = 'cms'

urlpatterns = [
    # ================ CMS Public Read Endpoints ===============
    path('site-banners/', PublicSiteBannerListView.as_view(), name='public-site-banners'),
    path('promo-banners/', PublicPromoBannerListView.as_view(), name='public-promo-banners'),
    path('public/page-contents/', PublicPageContentListView.as_view(), name='public-page-contents'),
    path('blogs/', PublicBlogListView.as_view(), name='public-blog-list'),
    path('blogs/<slug:slug>/', PublicBlogDetailView.as_view(), name='public-blog-detail'),
    # ============== End Public Read Endpoints ==============

    # ================ CMS Dashboard Admin CRUD Endpoints ===============
    path('admin/site-banners/', SiteBannerListAPIView.as_view(), name='site-banner-list'),
    path('admin/site-banners/create/', SiteBannerCreateAPIView.as_view(), name='site-banner-create'),
    path('admin/site-banners/<int:pk>/', SiteBannerRetrieveAPIView.as_view(), name='site-banner-detail'),
    path('admin/site-banners/<int:pk>/update/', SiteBannerUpdateAPIView.as_view(), name='site-banner-update'),
    path('admin/site-banners/<int:pk>/delete/', SiteBannerDeleteAPIView.as_view(), name='site-banner-delete'),

    path('admin/promo-banners/', PromoBannerListAPIView.as_view(), name='promo-banner-list'),
    path('admin/promo-banners/create/', PromoBannerCreateAPIView.as_view(), name='promo-banner-create'),
    path('admin/promo-banners/<int:pk>/', PromoBannerRetrieveAPIView.as_view(), name='promo-banner-detail'),
    path('admin/promo-banners/<int:pk>/update/', PromoBannerUpdateAPIView.as_view(), name='promo-banner-update'),
    path('admin/promo-banners/<int:pk>/delete/', PromoBannerDeleteAPIView.as_view(), name='promo-banner-delete'),

    path('admin/page-content/', PageContentListAPIView.as_view(), name='page-content-list'),
    path('admin/page-content/create/', PageContentCreateAPIView.as_view(), name='page-content-create'),
    path('admin/page-content/<int:pk>/', PageContentRetrieveAPIView.as_view(), name='page-content-detail'),
    path('admin/page-content/<int:pk>/update/', PageContentUpdateAPIView.as_view(), name='page-content-update'),
    path('admin/page-content/<int:pk>/delete/', PageContentDeleteAPIView.as_view(), name='page-content-delete'),

    path('admin/blog-categories/', BlogCategoryListAPIView.as_view(), name='blog-category-list'),
    path('admin/blog-categories/create/', BlogCategoryCreateAPIView.as_view(), name='blog-category-create'),
    path('admin/blog-categories/<int:pk>/', BlogCategoryRetrieveAPIView.as_view(), name='blog-category-detail'),
    path('admin/blog-categories/<int:pk>/update/', BlogCategoryUpdateAPIView.as_view(), name='blog-category-update'),
    path('admin/blog-categories/<int:pk>/delete/', BlogCategoryDeleteAPIView.as_view(), name='blog-category-delete'),

    path('admin/blogs/', DashboardBlogListAPIView.as_view(), name='blog-list'),
    path('admin/blogs/create/', DashboardBlogCreateAPIView.as_view(), name='blog-create'),
    path('admin/blogs/<int:pk>/', DashboardBlogRetrieveAPIView.as_view(), name='blog-detail'),
    path('admin/blogs/<int:pk>/update/', DashboardBlogUpdateAPIView.as_view(), name='blog-update'),
    path('admin/blogs/<int:pk>/delete/', DashboardBlogDeleteAPIView.as_view(), name='blog-delete'),
    # ============== End CMS Dashboard Admin CRUD Endpoints ==============
]