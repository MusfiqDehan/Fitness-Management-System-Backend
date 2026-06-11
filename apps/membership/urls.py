from django.urls import path
from .views import (
    MemberPackageView,
    MemberView,
    MemberImportAPIView,
    MemberLookupAPIView,
    MemberAnalyticsAPIView,
    InviteMemberAPIView,
    VerifyInvitationAPIView,
    CompleteMemberRegistrationAPIView,
    PaymentView,
    PaymentAnalyticsAPIView,
    MemberMySubscriptionAPIView,
    AttendanceView,
    GymClassView,
    GymScheduleView,
    UnifiedClassListAPIView,
    UnifiedScheduleListAPIView,
    PublicMemberRegistrationAPIView,
    PublicPackageListAPIView,
    PublicPackageRetrieveAPIView,
    PublicGymClassListAPIView,
    PublicGymScheduleListAPIView,
)

app_name = 'membership'

urlpatterns = [
    # ========== MEMBER PACKAGES ==========
    # GET/POST         /packages/                          → list / create
    # GET/PUT/PATCH/DELETE /packages/{pk}/                 → retrieve / update / soft delete
    # PATCH            /packages/{pk}/?action=activate|deactivate|publish|unpublish|highlight
    path('packages/', MemberPackageView.as_view(), name='package-list'),
    path('packages/<int:pk>/', MemberPackageView.as_view(), name='package-detail'),

    # ========== MEMBERS ==========
    # GET/POST         /members/                            → list / create
    # GET/PUT/PATCH/DELETE /members/{pk}/                   → retrieve / update / soft delete
    # PATCH            /members/{pk}/?action=activate|deactivate|restore|resend_invitation
    path('members/', MemberView.as_view(), name='member-list'),
    path('members/import/', MemberImportAPIView.as_view(), name='member-import'),
    path('members/<int:pk>/', MemberView.as_view(), name='member-detail'),
    path('members/lookup/', MemberLookupAPIView.as_view(), name='member-lookup'),
    path('members/analytics/', MemberAnalyticsAPIView.as_view(), name='member-analytics'),
    path('members/invite/', InviteMemberAPIView.as_view(), name='member-invite'),

    # ========== PAYMENTS ==========
    path('payments/', PaymentView.as_view(), name='payment-list'),
    path('payments/<int:pk>/', PaymentView.as_view(), name='payment-detail'),
    path('payments/analytics/', PaymentAnalyticsAPIView.as_view(), name='payment-analytics'),
    path('my-subscription/', MemberMySubscriptionAPIView.as_view(), name='member-my-subscription'),

    # ========== ATTENDANCE ==========
    path('attendance/', AttendanceView.as_view(), name='attendance-list'),

    # ========== GYM CLASSES & SCHEDULES ==========
    path('gym-classes/', GymClassView.as_view(), name='gymclass-list'),
    path('gym-classes/<int:pk>/', GymClassView.as_view(), name='gymclass-detail'),
    path('gym-schedules/', GymScheduleView.as_view(), name='gymschedule-list'),
    path('gym-schedules/<int:pk>/', GymScheduleView.as_view(), name='gymschedule-detail'),
    path('unified-classes/', UnifiedClassListAPIView.as_view(), name='unified-class-list'),
    path('unified-schedules/', UnifiedScheduleListAPIView.as_view(), name='unified-schedule-list'),

    # ========== PUBLIC (Landing Page) ==========
    path('public/register/', PublicMemberRegistrationAPIView.as_view(), name='public-register'),
    path('public/packages/', PublicPackageListAPIView.as_view(), name='public-packages-list'),
    path('public/packages/<int:pk>/', PublicPackageRetrieveAPIView.as_view(), name='public-packages-detail'),
    path('public/verify-invitation/', VerifyInvitationAPIView.as_view(), name='verify-invitation'),
    path('public/complete-registration/', CompleteMemberRegistrationAPIView.as_view(), name='complete-registration'),
    path('public/gym-classes/', PublicGymClassListAPIView.as_view(), name='public-gymclass-list'),
    path('public/gym-schedules/', PublicGymScheduleListAPIView.as_view(), name='public-gymschedule-list'),
]
