from django.contrib import admin
from django.urls import path, include,re_path
from django.views.static import serve
from django.conf import settings
from django.conf.urls.static import static
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)


urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('main_app.urls')),
    path('api/accounts/', include('accounts.urls')),
    path('api/dashboard/', include('dashboard.urls')),
    path('api/membership/', include('membership_management.urls')),
    path('api/login/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
]

urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
# remove the DEBUG check for media, optional now
# urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
# Dynamic mapping for all top-level media folders
media_folders = ['gym_clubs', 'blogs', 'banners','gym_classes']

for folder in media_folders:
    urlpatterns += [
        re_path(rf'^{folder}/(?P<path>.*)$', serve, {
            'document_root': settings.STATIC_ROOT / folder,
        })
    ]

