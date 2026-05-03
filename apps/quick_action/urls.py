from django.urls import path
from .views import (
    BannerListAPIView,
    BannerCreateAPIView,
    BannerRetrieveAPIView,
    BannerUpdateAPIView,
    BannerDeleteAPIView,
    GymClubListAPIView,
    GymClubCreateAPIView,
    GymClubRetrieveAPIView,
    GymClubUpdateAPIView,
    GymClubDeleteAPIView,
    CategoryListCreateView,
    ScheduleListCreateView,
    GymClassListCreateView,
    GymClassDetailView,
    BlogCategoryListAPIView,
    BlogCategoryCreateAPIView,
    BlogCategoryRetrieveAPIView,
    BlogCategoryUpdateAPIView,
    BlogCategoryDeleteAPIView,
    ContactCreateAPIView,
    FitHiveSupportCreateAPIView,
    PublicBlogListView,
    PublicBlogDetailView,
    PublicPackageListAPIView,
    PublicPackageRetrieveAPIView,
    PublicSiteBannerListView,
    PublicPromoBannerListView,
    PublicSiteSettingsView,
    PublicPageContentListView,
    PublicGymScheduleListView,
)

app_name = 'quick_action'

urlpatterns = [
    path('banners/', BannerListAPIView.as_view(), name='banner-list'),
    path('banners/create/', BannerCreateAPIView.as_view(), name='banner-create'),
    path('banners/<int:pk>/', BannerRetrieveAPIView.as_view(), name='banner-detail'),
    path('banners/<int:pk>/update/', BannerUpdateAPIView.as_view(), name='banner-update'),
    path('banners/<int:pk>/delete/', BannerDeleteAPIView.as_view(), name='banner-delete'),
    
    path('blog-categories/', BlogCategoryListAPIView.as_view(), name='blog-category-list'),
    path('blog-categories/create/', BlogCategoryCreateAPIView.as_view(), name='blog-category-create'),
    path('blog-categories/<int:pk>/', BlogCategoryRetrieveAPIView.as_view(), name='blog-category-detail'),
    path('blog-categories/<int:pk>/update/', BlogCategoryUpdateAPIView.as_view(), name='blog-category-update'),
    path('blog-categories/<int:pk>/delete/', BlogCategoryDeleteAPIView.as_view(), name='blog-category-delete'),
    
    # Public read-only endpoints (no auth required)
    path('blogs/', PublicBlogListView.as_view()),
    path('blogs/<slug:slug>/', PublicBlogDetailView.as_view()),
    path('site-banners/', PublicSiteBannerListView.as_view(), name='public-site-banners'),
    path('promo-banners/', PublicPromoBannerListView.as_view(), name='public-promo-banners'),
    path('site-settings/', PublicSiteSettingsView.as_view(), name='public-site-settings'),
    path('page-contents/', PublicPageContentListView.as_view(), name='public-page-contents'),
    path('gym-schedules/', PublicGymScheduleListView.as_view(), name='public-gym-schedules'),
    # ==============
    
    path('gym-club/', GymClubListAPIView.as_view(), name='gym-club-list'),
    path('gym-club/create/', GymClubCreateAPIView.as_view(), name='gym-club-create'),
    path('gym-club/<int:pk>/', GymClubRetrieveAPIView.as_view(), name='gym-club-detail'),
    path('gym-club/<int:pk>/update/', GymClubUpdateAPIView.as_view(), name='gym-club-update'),
    path('gym-club/<int:pk>/delete/', GymClubDeleteAPIView.as_view(), name='gym-club-delete'),
    path('packages/', PublicPackageListAPIView.as_view(), name='public-packages-list'),
    path('packages/<int:pk>/', PublicPackageRetrieveAPIView.as_view(), name='public-packages-detail'),
    path("categories/", CategoryListCreateView.as_view()),
    path("schedules/", ScheduleListCreateView.as_view()),
    path("classes/", GymClassListCreateView.as_view()),
    path("classes/<int:pk>/", GymClassDetailView.as_view()),
    
    path("contact/", ContactCreateAPIView.as_view(), name="contact-create"),
    path("fithive-support/", FitHiveSupportCreateAPIView.as_view(), name="fithive-support-create"),
    
]
