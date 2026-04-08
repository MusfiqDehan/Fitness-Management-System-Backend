from rest_framework.routers import DefaultRouter
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
    AttendanceDashboardViewSet
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

urlpatterns = router.urls
