from django.urls import path

from .views import (
    FeatureListAPIView,
    PackageDetailAPIView,
    PackageFeaturesAPIView,
    PackageListCreateAPIView,
    PaymentAPIView,
    PaymentStatsAPIView,
    PaymentMemberListAPIView,
    PaymentInvoicePdfAPIView,
)

app_name = 'billing'

urlpatterns = [
    path('features/', FeatureListAPIView.as_view(), name='feature-list'),
    path('packages/', PackageListCreateAPIView.as_view(), name='package-list-create'),
    path('packages/<int:pk>/', PackageDetailAPIView.as_view(), name='package-detail'),
    path('packages/<int:pk>/features/', PackageFeaturesAPIView.as_view(), name='package-features'),
    path('payments/', PaymentAPIView.as_view(), name='payment-list-create'),
    path('payments/stats/', PaymentStatsAPIView.as_view(), name='payment-stats'),
    path('payments/members/', PaymentMemberListAPIView.as_view(), name='payment-member-options'),
    path('payments/<int:pk>/invoice/', PaymentInvoicePdfAPIView.as_view(), name='payment-invoice-pdf'),
    path('payments/<int:pk>/', PaymentAPIView.as_view(), name='payment-detail'),
]

