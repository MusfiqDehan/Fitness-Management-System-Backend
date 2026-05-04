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
from config.health import tenant_health



urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/', include(('apps.quick_action.urls', 'quick_action'), namespace='quick_action')),
    path('api/v1/health/tenant/', tenant_health, name='tenant-health'),
    path('api/v1/identity/', include(('apps.identity.urls', 'identity'), namespace='identity')),
    path('api/v1/dashboard/', include(('apps.dashboard.urls', 'dashboard'), namespace='dashboard')),
    path('api/v1/membership/', include(('apps.membership.urls', 'membership'), namespace='membership')),

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

