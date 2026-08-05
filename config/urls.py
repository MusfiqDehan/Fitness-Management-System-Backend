"""
URL configuration for TENANT schemas (ROOT_URLCONF).

These routes are active when a request resolves to a specific tenant
schema via TenantMainMiddleware (hostname matches a Domain record).

Public-schema / admin routes live in config/public_urls.py
(PUBLIC_SCHEMA_URLCONF).
"""
from django.contrib import admin
from django.urls import path, include, re_path
from django.views.static import serve
from django.conf import settings
from django.conf.urls.static import static

from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView
from config.health import liveness_health, readiness_health, tenant_health
from apps.attendance.views import IclockCdataAPIView, IclockGetRequestAPIView, IclockDeviceCmdAPIView
from apps.dashboard.settings_views import PublicGymBrandingView



urlpatterns = [
    # Django Admin
    path('ninja/', admin.site.urls),

    # Health Check
    path('api/v1/health/tenant/', tenant_health, name='tenant-health'),
    path('api/v1/health/live/', liveness_health, name='liveness-health'),
    path('api/v1/health/ready/', readiness_health, name='readiness-health'),

    # Public gym branding (read-only) — backwards-compatible URL for the frontend.
    # On a tenant schema this is backed by GymProfile.
    path('api/v1/cms/public/site-settings/', PublicGymBrandingView.as_view(), name='public-gym-branding'),

    # App-specific API routes
    path('api/v1/', include(('apps.quick_action.urls', 'quick_action'), namespace='quick_action')),
    path('api/v1/dashboard/', include(('apps.dashboard.urls', 'dashboard'), namespace='dashboard')),

    path('api/v1/tenancy/', include(('apps.tenancy.urls', 'tenancy'), namespace='tenancy')),
    path('api/v1/identity/', include(('apps.identity.urls', 'identity'), namespace='identity')),
    path('api/v1/cms/', include(('apps.cms.urls', 'cms'), namespace='cms')),
    path('api/v1/crm/', include(('apps.crm.urls', 'crm'), namespace='crm')),
    path('api/v1/membership/', include(('apps.membership.urls', 'membership'), namespace='membership')),
    path('api/v1/access/', include(('apps.access.urls', 'access'), namespace='access')),
    path('api/v1/billing/', include(('apps.billing.urls', 'billing'), namespace='billing')),
    path('api/v1/reminder/', include(('apps.reminder.urls', 'reminder'), namespace='reminder')),
    path('api/v1/attendance/', include(('apps.attendance.urls', 'attendance'), namespace='attendance')),
    path('api/v1/trainer/', include(('apps.trainer.urls', 'trainer'), namespace='trainer')),
    path('api/v1/branch/', include(('apps.gym_branch.urls', 'gym_branch'), namespace='gym_branch')),

    # ZKTeco ADMS device paths.
    # Accept both with and without a trailing slash because F18 firmware often
    # calls /iclock/cdata (no slash) and will not follow Django's 301 redirect.
    re_path(r'^iclock/cdata/?$', IclockCdataAPIView.as_view(), name='iclock-cdata-short'),
    re_path(r'^iclock/getrequest/?$', IclockGetRequestAPIView.as_view(), name='iclock-getrequest-short'),
    re_path(r'^iclock/devicecmd/?$', IclockDeviceCmdAPIView.as_view(), name='iclock-devicecmd-short'),
    # Root-level fallback for firmware that does NOT prepend /iclock/
    re_path(r'^cdata/?$', IclockCdataAPIView.as_view(), name='iclock-cdata-root'),
    re_path(r'^getrequest/?$', IclockGetRequestAPIView.as_view(), name='iclock-getrequest-root'),
    re_path(r'^devicecmd/?$', IclockDeviceCmdAPIView.as_view(), name='iclock-devicecmd-root'),

    # API Schema & Docs (tenant-scoped)
    path('api/v1/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/v1/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/v1/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
]

urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

# Serve media files (works even when DEBUG=False for local development)
urlpatterns += [
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
]

