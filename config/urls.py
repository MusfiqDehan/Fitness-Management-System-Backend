from django.contrib import admin
from django.urls import path, include,re_path
from django.views.static import serve
from django.conf import settings
from django.conf.urls.static import static
from rest_framework_simplejwt.views import (
    TokenRefreshView,
)
from apps.accounts.views import EmailOrPhoneTokenObtainPairView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView


urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include(('apps.quick_action.urls', 'quick_action'), namespace='quick_action')),
    path('api/accounts/', include(('apps.accounts.urls', 'accounts'), namespace='accounts')),
    path('api/dashboard/', include(('apps.dashboard.urls', 'dashboard'), namespace='dashboard')),
    path('api/membership/', include('apps.membership_management.urls')),
    path('api/tenancy/', include(('apps.tenancy.urls', 'tenancy'), namespace='tenancy')),
    path('api/login/', EmailOrPhoneTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    # API Schema & Docs
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
]

urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

# Serve media files (works even when DEBUG=False for local development)
urlpatterns += [
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
]

