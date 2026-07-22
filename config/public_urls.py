"""
URL configuration for the PUBLIC (shared) PostgreSQL schema.

These routes are served when a request's hostname resolves to the
public schema — typically the root/admin domain (e.g. app.example.com
or localhost without a tenant subdomain).

Tenant-facing API routes live in config/urls.py (ROOT_URLCONF).
"""
from django.contrib import admin
from django.urls import path, include, re_path
from django.views.static import serve
from django.conf import settings
from django.conf.urls.static import static
from config.health import liveness_health, readiness_health, tenant_health

from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)
from apps.attendance.views import IclockCdataAPIView, IclockDeviceCmdAPIView, IclockGetRequestAPIView
from apps.trainer.views import TrainerPublicProfileView, VerifyTrainerInvitationAPIView, CompleteTrainerRegistrationAPIView
from apps.tenancy.platform_settings_views import (
    PlatformGymProfileView,
    PlatformGymPreferencesView,
    PlatformNotificationPreferencesView,
    PlatformFileUploadView,
    PlatformPublicGymBrandingView,
)

urlpatterns = [
    # Django admin (manages Tenant + Domain records)
    path('admin/', admin.site.urls),

    # Tenant routing health check
    path('api/v1/health/tenant/', tenant_health, name='tenant-health'),
    path('api/v1/health/live/', liveness_health, name='liveness-health'),
    path('api/v1/health/ready/', readiness_health, name='readiness-health'),

    # Public platform branding — same URL shape as tenant PublicGymBrandingView.
    # Must stay above the cms.urls include so it is not shadowed by CMS PageContent routes.
    path('api/v1/cms/public/site-settings/', PlatformPublicGymBrandingView.as_view(), name='platform-public-gym-branding'),

    # Dual-schema CMS (blogs/banners) — same paths as tenant ROOT_URLCONF.
    path('api/v1/cms/', include(('apps.cms.urls', 'cms'), namespace='cms')),

    # Public control-plane authentication
    path('api/v1/identity/', include(('apps.identity.urls', 'identity'), namespace='public-identity')),

    # Tenant provisioning / management API
    path('api/v1/tenancy/', include(('apps.tenancy.urls', 'tenancy'), namespace='tenancy-v1')),
    path('api/v1/tenants/', include(('apps.tenancy.urls', 'tenancy'), namespace='tenancy')),

    # Platform-admin billing & package management
    path('api/v1/billing/', include(('apps.billing.public_urls', 'billing'), namespace='billing')),

    # Public contact-us form submissions
    path('api/v1/crm/', include(('apps.crm.public_urls', 'crm'), namespace='crm')),

    # Notification endpoints for platform admin
    path('api/v1/reminder/', include(('apps.reminder.urls', 'reminder'), namespace='public-reminder')),

    # Trainer public routes (no tenant scope needed)
    path('api/v1/trainer/public/profile/<slug:username>/', TrainerPublicProfileView.as_view(), name='trainer-public-profile'),
    path('api/v1/trainer/public/verify-invitation/', VerifyTrainerInvitationAPIView.as_view(), name='trainer-verify-invitation'),
    path('api/v1/trainer/public/complete-registration/', CompleteTrainerRegistrationAPIView.as_view(), name='trainer-complete-registration'),

    # Platform Admin settings — mirror of the tenant dashboard settings endpoints.
    # Backed by public-schema singleton models so the shared Settings page works
    # for platform admin users without touching tenant-schema tables.
    path('api/v1/dashboard/settings/gym-profile/', PlatformGymProfileView.as_view(), name='platform-settings-gym-profile'),
    path('api/v1/dashboard/settings/preferences/', PlatformGymPreferencesView.as_view(), name='platform-settings-preferences'),
    path('api/v1/dashboard/settings/notifications/', PlatformNotificationPreferencesView.as_view(), name='platform-settings-notifications'),
    path('api/v1/dashboard/upload/', PlatformFileUploadView.as_view(), name='platform-file-upload'),

    # Public-host ADMS device ingress. These views resolve SN -> tenant schema
    # before touching tenant-only attendance tables.
    re_path(r'^iclock/cdata/?$', IclockCdataAPIView.as_view(), name='public-iclock-cdata-short'),
    re_path(r'^iclock/getrequest/?$', IclockGetRequestAPIView.as_view(), name='public-iclock-getrequest-short'),
    re_path(r'^iclock/devicecmd/?$', IclockDeviceCmdAPIView.as_view(), name='public-iclock-devicecmd-short'),
    re_path(r'^cdata/?$', IclockCdataAPIView.as_view(), name='public-iclock-cdata-root'),
    re_path(r'^getrequest/?$', IclockGetRequestAPIView.as_view(), name='public-iclock-getrequest-root'),
    re_path(r'^devicecmd/?$', IclockDeviceCmdAPIView.as_view(), name='public-iclock-devicecmd-root'),

    # API Schema & Docs (shared)
    path('api/v1/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/v1/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/v1/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
]

urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

urlpatterns += [
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
]
