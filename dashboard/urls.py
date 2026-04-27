from rest_framework.routers import DefaultRouter
from django.urls import path
from .views import (
    DashboardBlogViewSet, 
    DashboardBlogCategoryViewSet, 
    GymClassDashboardViewSet,
    ClassBookingViewSet,
    GymClassCategoryDashboardViewSet,
    DashboardContactViewSet,
    DashboardFitHiveSupportViewSet,
    PackageViewSet,
    GymClubDashboardViewSet,
    PackageDashboardViewSet,
    MemberDashboardViewSet,
    PaymentDashboardViewSet,
    AttendanceDashboardViewSet,
    SiteBannerViewSet,
    PromoBannerViewSet,
    SiteSettingsAPIView,
    PageContentViewSet,
    FileUploadView,
)
from accounts.views import InstructorViewSet

router = DefaultRouter()
router.register('blogs', DashboardBlogViewSet)
router.register('blog-categories', DashboardBlogCategoryViewSet)
router.register('gym-classes', GymClassDashboardViewSet)
router.register(r'class-bookings', ClassBookingViewSet, basename='class-bookings')
router.register('gym-class-categories', GymClassCategoryDashboardViewSet)
router.register('instructors', InstructorViewSet, basename='instructor')
router.register('contacts', DashboardContactViewSet, basename='contacts')
router.register("fithive-support", DashboardFitHiveSupportViewSet, basename="fithive-support")
router.register('packages', PackageViewSet, basename='packages')
router.register(r'gym-club', GymClubDashboardViewSet, basename='gym-club')
router.register(r'members', MemberDashboardViewSet, basename='dashboard-members')
router.register(r'member-packages', PackageDashboardViewSet, basename='member-packages')
router.register(r'payments', PaymentDashboardViewSet, basename='dashboard-payments')
router.register(r'attendance', AttendanceDashboardViewSet, basename='dashboard-attendance')
router.register(r'site-banners', SiteBannerViewSet, basename='site-banners')
router.register(r'promo-banners', PromoBannerViewSet, basename='promo-banners')
router.register(r'page-content', PageContentViewSet, basename='page-content')

urlpatterns = router.urls + [
    path('site-settings/', SiteSettingsAPIView.as_view(), name='site-settings'),
    path('upload/', FileUploadView.as_view(), name='file-upload'),
]
