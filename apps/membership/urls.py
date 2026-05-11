from django.urls import path
from .views import (
    # Consolidated views
    MemberPackageView,
    MemberView,
    PaymentView,
    AttendanceView,
    # Public Views
    PublicMemberRegistrationAPIView,
    PublicPackageListAPIView,
    PublicPackageRetrieveAPIView,
    # Member Lookup
    MemberLookupAPIView,
)

app_name = 'membership'

urlpatterns = [
    # ========== MEMBER PACKAGES ==========
    # GET/POST    /packages/                → list / create
    # GET/PUT/PATCH/DELETE /packages/{pk}/  → retrieve / update / soft delete
    # PATCH       /packages/{pk}/?action=activate|deactivate|highlight
    path('packages/', MemberPackageView.as_view(), name='package-list'),
    path('packages/<int:pk>/', MemberPackageView.as_view(), name='package-detail'),

    # ========== MEMBERS ==========
    # GET/POST    /members/                  → list / create
    # GET/PUT/PATCH/DELETE /members/{pk}/  → retrieve / update / soft delete
    # PATCH       /members/{pk}/?action=activate|deactivate|restore
    path('members/', MemberView.as_view(), name='member-list'),
    path('members/<int:pk>/', MemberView.as_view(), name='member-detail'),
    path('members/lookup/', MemberLookupAPIView.as_view(), name='member-lookup'),

    # ========== PAYMENTS ==========
    # GET /payments/           → list
    # GET /payments/{pk}/      → retrieve
    path('payments/', PaymentView.as_view(), name='payment-list'),
    path('payments/<int:pk>/', PaymentView.as_view(), name='payment-detail'),

    # ========== ATTENDANCE ==========
    # GET /attendance/          → list
    path('attendance/', AttendanceView.as_view(), name='attendance-list'),

    # ========== PUBLIC (Landing Page) ==========
    path('public/register/', PublicMemberRegistrationAPIView.as_view(), name='public-register'),
    path('public/packages/', PublicPackageListAPIView.as_view(), name='public-packages-list'),
    path('public/packages/<int:pk>/', PublicPackageRetrieveAPIView.as_view(), name='public-packages-detail')
]