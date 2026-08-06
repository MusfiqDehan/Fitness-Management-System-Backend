from django.urls import path

from .views import (
    FeatureListAPIView,
    PackageDetailAPIView,
    PackageFeaturesAPIView,
    PackageListCreateAPIView,
    PaymentGatewayDetailAPIView,
    PaymentGatewayListAPIView,
    PaymentGatewaySetDefaultView,
    PaymentGatewayToggleAPIView,
    PlatformPricingConfigAPIView,
    PlatformSubscriptionInvoicePdfView,
    PlatformGatewaySubscriptionView,
    PlatformManualSubscriptionView,
    PlatformSubscriptionPaymentDetailView,
    PlatformSubscriptionPaymentsView,
    SubscriptionAvailableGatewaysView,
    SubscriptionPaymentCancelView,
    SubscriptionPaymentFailView,
    SubscriptionPaymentIPNView,
    SubscriptionPaymentSuccessView,
)

app_name = 'billing'

urlpatterns = [
    path('features/', FeatureListAPIView.as_view(), name='feature-list'),
    path('pricing-config/', PlatformPricingConfigAPIView.as_view(), name='pricing-config'),
    path('packages/', PackageListCreateAPIView.as_view(), name='package-list-create'),
    path('packages/<int:pk>/', PackageDetailAPIView.as_view(), name='package-detail'),
    path('packages/<int:pk>/features/', PackageFeaturesAPIView.as_view(), name='package-features'),
    # Payment gateway management (platform admin, public schema)
    path('gateways/', PaymentGatewayListAPIView.as_view(), name='gateway-list-create'),
    path('gateways/<slug:slug>/', PaymentGatewayDetailAPIView.as_view(), name='gateway-detail'),
    path('gateways/<slug:slug>/toggle/', PaymentGatewayToggleAPIView.as_view(), name='gateway-toggle'),
    path('gateways/<slug:slug>/set-default-subscription/', PaymentGatewaySetDefaultView.as_view(), name='gateway-set-default'),
    # Subscription payment callbacks (public schema, called by SSLCommerz)
    path('subscription/available-gateways/', SubscriptionAvailableGatewaysView.as_view(), name='subscription-available-gateways'),
    path('subscription/ipn/', SubscriptionPaymentIPNView.as_view(), name='subscription-ipn'),
    path('subscription/success/', SubscriptionPaymentSuccessView.as_view(), name='subscription-success'),
    path('subscription/fail/', SubscriptionPaymentFailView.as_view(), name='subscription-fail'),
    path('subscription/cancel/', SubscriptionPaymentCancelView.as_view(), name='subscription-cancel'),
    # Platform admin: subscription payment tracking
    path('subscription/payments/', PlatformSubscriptionPaymentsView.as_view(), name='platform-subscription-payments'),
    path(
        'subscription/payments/<int:pk>/',
        PlatformSubscriptionPaymentDetailView.as_view(),
        name='platform-subscription-payment-detail',
    ),
    path('subscription/payments/manual/', PlatformManualSubscriptionView.as_view(), name='platform-subscription-manual'),
    path('subscription/payments/gateway/', PlatformGatewaySubscriptionView.as_view(), name='platform-subscription-gateway'),
    path('subscription/payments/<int:pk>/invoice/', PlatformSubscriptionInvoicePdfView.as_view(), name='platform-subscription-invoice-pdf'),
]
