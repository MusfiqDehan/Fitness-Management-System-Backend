from django.urls import path
from .views import (
	TenantSelfRegistrationAPIView,
	SuperadminInvitationAPIView,
	InvitationValidationAPIView,
	PasswordSetupAPIView,
	TenantAuthenticationAPIView,
	PasswordResetRequestAPIView,
	PasswordResetConfirmAPIView,
	TenantAdminOverviewAPIView,
	TenantAdminListAPIView,
	TenantAdminDetailAPIView,
	TenantAdminActivationAPIView,
	TenantAuditLogListAPIView,
)

app_name = 'tenancy'

urlpatterns = [
	# Public onboarding and auth APIs
	path('register/', TenantSelfRegistrationAPIView.as_view(), name='tenant-register'),
	path('auth/login/', TenantAuthenticationAPIView.as_view(), name='tenant-auth-login'),
	path('tokens/validate/', InvitationValidationAPIView.as_view(), name='tenant-token-validate'),
	path('password/setup/', PasswordSetupAPIView.as_view(), name='tenant-password-setup'),
	path('password/reset/request/', PasswordResetRequestAPIView.as_view(), name='tenant-password-reset-request'),
	path('password/reset/confirm/', PasswordResetConfirmAPIView.as_view(), name='tenant-password-reset-confirm'),

	# Superadmin flows
	path('admin/invitations/', SuperadminInvitationAPIView.as_view(), name='tenant-admin-invite'),
	path('admin/overview/', TenantAdminOverviewAPIView.as_view(), name='tenant-admin-overview'),
	path('admin/tenants/', TenantAdminListAPIView.as_view(), name='tenant-admin-list'),
	path('admin/tenants/<int:pk>/', TenantAdminDetailAPIView.as_view(), name='tenant-admin-detail'),
	path('admin/tenants/<int:tenant_id>/activation/', TenantAdminActivationAPIView.as_view(), name='tenant-admin-activation'),
	path('admin/audit-logs/', TenantAuditLogListAPIView.as_view(), name='tenant-admin-audit-logs'),
]
