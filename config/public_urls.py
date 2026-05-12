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
from config.health import tenant_health

from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)
from apps.trainer.views import TrainerPublicProfileView, VerifyTrainerInvitationAPIView, CompleteTrainerRegistrationAPIView

urlpatterns = [
    # Django admin (manages Tenant + Domain records)
    path('admin/', admin.site.urls),

    # Tenant routing health check
    path('api/v1/health/tenant/', tenant_health, name='tenant-health'),

    # Public control-plane authentication
    path('api/v1/identity/', include(('apps.identity.urls', 'identity'), namespace='public-identity')),

    # Tenant provisioning / management API
    path('api/v1/tenancy/', include(('apps.tenancy.urls', 'tenancy'), namespace='tenancy-v1')),
    path('api/v1/tenants/', include(('apps.tenancy.urls', 'tenancy'), namespace='tenancy')),

    # Platform-admin billing & package management
    path('api/v1/billing/', include(('apps.billing.urls', 'billing'), namespace='billing')),

    # Trainer public routes (no tenant scope needed)
    path('api/v1/trainer/public/profile/<slug:username>/', TrainerPublicProfileView.as_view(), name='trainer-public-profile'),
    path('api/v1/trainer/public/verify-invitation/', VerifyTrainerInvitationAPIView.as_view(), name='trainer-verify-invitation'),
    path('api/v1/trainer/public/complete-registration/', CompleteTrainerRegistrationAPIView.as_view(), name='trainer-complete-registration'),

    # API Schema & Docs (shared)
    path('api/v1/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/v1/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/v1/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
]

urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

urlpatterns += [
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
]
