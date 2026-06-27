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
	TenantAdminInvitationDetailView,
	TenantAuditLogListAPIView,
	TenantMemberInviteAPIView,
	ChangePasswordView,
	PlatformSettingsAPIView,
)
from .rbac_views import (
	PlatformModuleListView,
	PlatformRoleListCreateView,
	PlatformRoleDetailView,
	PlatformRolePermissionsView,
	PlatformUserRoleListCreateView,
	PlatformUserRoleDetailView,
	FeatureListCreateView,
	FeatureDetailView,
	PublicPlatformPackageListView,
	PublicPlatformPricingConfigView,
	TenantCurrentSubscriptionView,
	PlatformPackageListCreateView,
	PlatformPackageDetailView,
	PlatformPackageFeaturesView,
	TenantFeatureFlagListView,
	TenantFeatureFlagResyncView,
	CurrentTenantFeatureListView,
	PublicTenantLandingStatusView,
	PlatformInvitationListCreateView,
	PlatformInvitationRevokeView,
	PlatformInviteValidateView,
	PlatformInviteAcceptView,
	MyPlatformPermissionsView,
	FeatureRegistryView,
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

	# Public packages (landing page pricing)
	path('packages/', PublicPlatformPackageListView.as_view(), name='public-packages'),
	path('packages/pricing-config/', PublicPlatformPricingConfigView.as_view(), name='public-pricing-config'),

	# Public tenant landing-page status (used by the tenant homepage on subdomains)
	path('public/landing-status/', PublicTenantLandingStatusView.as_view(), name='public-landing-status'),

	# Authenticated tenant feature lookup (used by frontend to know which features to show)
	path('me/features/', CurrentTenantFeatureListView.as_view(), name='current-tenant-features'),

	# Tenant subscription current plan (any authenticated tenant user)
	path('subscription/current/', TenantCurrentSubscriptionView.as_view(), name='tenant-subscription-current'),

	# Tenant staff member invitations (from Permissions page)
	path('members/invite/', TenantMemberInviteAPIView.as_view(), name='tenant-member-invite'),

	# Change password — available in both tenant and public schemas
	path('password/change/', ChangePasswordView.as_view(), name='password-change'),

	# Authenticated platform permission lookup (used by frontend to filter Platform Admin sidebar)
	path('admin/me/platform-permissions/', MyPlatformPermissionsView.as_view(), name='me-platform-permissions'),

	# Canonical feature registry (sidebar items for both scopes + shared)
	path('admin/feature-registry/', FeatureRegistryView.as_view(), name='feature-registry'),

	# Superadmin flows
	path('admin/invitations/', SuperadminInvitationAPIView.as_view(), name='tenant-admin-invite'),
	path('admin/invitations/<int:pk>/', TenantAdminInvitationDetailView.as_view(), name='tenant-admin-invitation-detail'),
	path('admin/overview/', TenantAdminOverviewAPIView.as_view(), name='tenant-admin-overview'),
	path('admin/tenants/', TenantAdminListAPIView.as_view(), name='tenant-admin-list'),
	path('admin/tenants/<int:pk>/', TenantAdminDetailAPIView.as_view(), name='tenant-admin-detail'),
	path('admin/tenants/<int:tenant_id>/activation/', TenantAdminActivationAPIView.as_view(), name='tenant-admin-activation'),
	path('admin/audit-logs/', TenantAuditLogListAPIView.as_view(), name='tenant-admin-audit-logs'),

	# Platform RBAC (Phase 0)
	path('admin/platform-modules/', PlatformModuleListView.as_view(), name='platform-modules'),
	path('admin/platform-roles/', PlatformRoleListCreateView.as_view(), name='platform-roles'),
	path('admin/platform-roles/<int:pk>/', PlatformRoleDetailView.as_view(), name='platform-role-detail'),
	path('admin/platform-roles/<int:role_id>/permissions/', PlatformRolePermissionsView.as_view(), name='platform-role-permissions'),
	path('admin/platform-user-roles/', PlatformUserRoleListCreateView.as_view(), name='platform-user-roles'),
	path('admin/platform-user-roles/<int:pk>/', PlatformUserRoleDetailView.as_view(), name='platform-user-role-detail'),

	# Platform team email invitations (Phase 0)
	path('admin/platform-invitations/', PlatformInvitationListCreateView.as_view(), name='platform-invitations'),
	path('admin/platform-invitations/<int:pk>/', PlatformInvitationRevokeView.as_view(), name='platform-invitation-revoke'),
	path('platform-invitations/validate/', PlatformInviteValidateView.as_view(), name='platform-invitation-validate'),
	path('platform-invitations/accept/', PlatformInviteAcceptView.as_view(), name='platform-invitation-accept'),

	# Feature registry (Phase 1)
	path('admin/features/', FeatureListCreateView.as_view(), name='features'),
	path('admin/features/<int:pk>/', FeatureDetailView.as_view(), name='feature-detail'),

	# Platform packages management (Phase 1)
	path('admin/packages/', PlatformPackageListCreateView.as_view(), name='admin-packages'),
	path('admin/packages/<int:pk>/', PlatformPackageDetailView.as_view(), name='admin-package-detail'),
	path('admin/packages/<int:package_id>/features/', PlatformPackageFeaturesView.as_view(), name='admin-package-features'),

	# Per-tenant feature overrides (Phase 1)
	path('admin/tenants/<int:tenant_id>/features/', TenantFeatureFlagListView.as_view(), name='tenant-features'),
	path('admin/tenants/<int:tenant_id>/features/resync/', TenantFeatureFlagResyncView.as_view(), name='tenant-features-resync'),

	# Platform-wide settings (singleton, platform.settings feature-gated)
	path('admin/platform-settings/', PlatformSettingsAPIView.as_view(), name='platform-settings'),
]

