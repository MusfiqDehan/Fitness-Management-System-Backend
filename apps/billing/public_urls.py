from django.urls import path

from .views import (
    FeatureListAPIView,
    PackageDetailAPIView,
    PackageFeaturesAPIView,
    PackageListCreateAPIView,
)

app_name = 'billing'

urlpatterns = [
    path('features/', FeatureListAPIView.as_view(), name='feature-list'),
    path('packages/', PackageListCreateAPIView.as_view(), name='package-list-create'),
    path('packages/<int:pk>/', PackageDetailAPIView.as_view(), name='package-detail'),
    path('packages/<int:pk>/features/', PackageFeaturesAPIView.as_view(), name='package-features'),
]
