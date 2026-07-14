from django.urls import path

from .views import (
    AvailableGatewaysView,
    FeatureListAPIView,
    PackageDetailAPIView,
    PackageFeaturesAPIView,
    PackageListCreateAPIView,
    PaymentAPIView,
    PaymentCancelView,
    PaymentExportAPIView,
    PaymentFailView,
    PaymentInitiateView,
    PaymentInvoicePdfAPIView,
    PaymentIPNView,
    PaymentMemberListAPIView,
    PaymentStatsAPIView,
    PaymentSuccessView,
    PlatformPricingConfigAPIView,
    SubscriptionInvoiceListView,
    SubscriptionInvoicePdfView,
    TenantGatewayConfigView,
    TenantInitiateSubscriptionChangeView,
    TenantSubscriptionInvoiceAdminView,
    TenantSubscriptionInvoiceAdminPdfView,
    SubscriptionSummaryView,
)

app_name = 'billing'

urlpatterns = [
    path('features/', FeatureListAPIView.as_view(), name='feature-list'),
    path('pricing-config/', PlatformPricingConfigAPIView.as_view(), name='pricing-config'),
    path('packages/', PackageListCreateAPIView.as_view(), name='package-list-create'),
    path('packages/<int:pk>/', PackageDetailAPIView.as_view(), name='package-detail'),
    path('packages/<int:pk>/features/', PackageFeaturesAPIView.as_view(), name='package-features'),
    # Payment CRUD
    path('payments/', PaymentAPIView.as_view(), name='payment-list-create'),
    path('payments/export/', PaymentExportAPIView.as_view(), name='payment-export'),
    path('payments/stats/', PaymentStatsAPIView.as_view(), name='payment-stats'),
    path('payments/members/', PaymentMemberListAPIView.as_view(), name='payment-member-options'),
    path('payments/<int:pk>/invoice/', PaymentInvoicePdfAPIView.as_view(), name='payment-invoice-pdf'),
    path('payments/<int:pk>/', PaymentAPIView.as_view(), name='payment-detail'),
    # Online payment gateway (tenant-scoped)
    path('payments/gateways/', TenantGatewayConfigView.as_view(), name='tenant-gateway-list'),
    path('payments/gateways/<int:pk>/', TenantGatewayConfigView.as_view(), name='tenant-gateway-detail'),
    path('payments/available-gateways/', AvailableGatewaysView.as_view(), name='available-gateways'),
    path('payments/initiate/', PaymentInitiateView.as_view(), name='payment-initiate'),
    # SSLCommerz callbacks (AllowAny — hit by gateway directly or browser redirect)
    path('payments/ipn/', PaymentIPNView.as_view(), name='payment-ipn'),
    path('payments/success/', PaymentSuccessView.as_view(), name='payment-success'),
    path('payments/fail/', PaymentFailView.as_view(), name='payment-fail'),
    path('payments/cancel/', PaymentCancelView.as_view(), name='payment-cancel'),
    # Tenant subscription invoice history (public schema read via schema_context)
    path('subscription/invoices/', SubscriptionInvoiceListView.as_view(), name='subscription-invoice-list'),
    path('subscription/invoices/<int:pk>/invoice/', SubscriptionInvoicePdfView.as_view(), name='subscription-invoice-pdf'),
    # Tenant subscription plan change & admin invoice view (no payments feature gate)
    path('subscription/initiate-change/', TenantInitiateSubscriptionChangeView.as_view(), name='subscription-initiate-change'),
    path('subscription/admin-invoices/', TenantSubscriptionInvoiceAdminView.as_view(), name='subscription-admin-invoices'),
    path(
        'subscription/admin-invoices/<int:pk>/invoice/',
        TenantSubscriptionInvoiceAdminPdfView.as_view(),
        name='subscription-admin-invoice-pdf',
    ),
    path('subscription/summary/', SubscriptionSummaryView.as_view(), name='subscription-summary'),
]

