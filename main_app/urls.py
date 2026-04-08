from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    BannerViewSet,
    GymClubViewSet,
    CategoryListCreateView,
    ScheduleListCreateView,
    GymClassListCreateView,
    GymClassDetailView,
    PublicBlogListView, 
    PublicBlogDetailView,
    BlogCategoryViewSet,
    ContactCreateAPIView,
    FitHiveSupportCreateAPIView,
    PublicPackageViewSet
)

router = DefaultRouter()
router.register('banners', BannerViewSet, basename='banner')
router.register(r'gym-club', GymClubViewSet, basename='gym-club')
router.register('blog-categories', BlogCategoryViewSet, basename='blog-category')  # 
router.register('packages', PublicPackageViewSet, basename='public-packages')

urlpatterns = [
    path('', include(router.urls)),
    path("categories/", CategoryListCreateView.as_view()),
    path("schedules/", ScheduleListCreateView.as_view()),
    path("classes/", GymClassListCreateView.as_view()),
    path("classes/<int:pk>/", GymClassDetailView.as_view()),
    path('blogs/', PublicBlogListView.as_view()),
    path('blogs/<slug:slug>/', PublicBlogDetailView.as_view()),
    path("contact/", ContactCreateAPIView.as_view(), name="contact-create"),
    path("fithive-support/", FitHiveSupportCreateAPIView.as_view(), name="fithive-support-create"),
]
