"""Serializers for the platform admin billing/packages management APIs.

These wrap the canonical models that live in `apps.tenancy` (public schema):
- Feature
- PlatformPackage
- PlatformPackageFeature

Kept inside the billing app so the platform admin's "Packages" section has
its own clean, focused API surface (separate from the broader RBAC views).
"""
from rest_framework import serializers

from apps.tenancy.models import (
    Feature,
    PlatformPackage,
    PlatformPackageFeature,
    PlatformPricingConfig,
    PaymentGateway,
)
from apps.membership.models import Member, Payment
from apps.billing.models import TenantPaymentGateway, PaymentTransaction


class FeatureSerializer(serializers.ModelSerializer):
    """Read-only feature row used by the package editor UI."""

    class Meta:
        model = Feature
        fields = [
            "id",
            "key",
            "name",
            "description",
            "parent",
            "is_system",
            "sort_order",
        ]
        read_only_fields = fields


class PackageFeatureSerializer(serializers.ModelSerializer):
    feature_key = serializers.CharField(source="feature.key", read_only=True)
    feature_name = serializers.CharField(source="feature.name", read_only=True)

    class Meta:
        model = PlatformPackageFeature
        fields = ["id", "feature", "feature_key", "feature_name", "is_enabled"]


class PackageSerializer(serializers.ModelSerializer):
    """Read/write serializer for a `PlatformPackage` plus enabled feature ids."""

    features = PackageFeatureSerializer(
        source="package_features", many=True, read_only=True
    )
    feature_ids = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False
    )

    class Meta:
        model = PlatformPackage
        fields = [
            "id",
            "slug",
            "name",
            "description",
            "price_monthly",
            "price_yearly",
            "max_users",
            "max_branches",
            "trial_days",
            "is_active",
            "is_public",
            "sort_order",
            "highlight",
            # pricing display customisation
            "badge_label",
            "cta_label",
            "setup_fee",
            "original_setup_fee",
            "original_price_monthly",
            "original_price_yearly",
            "included_items",
            "yearly_discount_percent",
            "price_custom_label",
            "price_period_label",
            "features",
            "feature_ids",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def _sync_features(self, package: PlatformPackage, feature_ids):
        wanted = set(feature_ids or [])
        existing = {
            pf.feature_id: pf
            for pf in PlatformPackageFeature.objects.filter(package=package)
        }
        for fid in wanted:
            pf = existing.get(fid)
            if pf is None:
                PlatformPackageFeature.objects.create(
                    package=package, feature_id=fid, is_enabled=True
                )
            elif not pf.is_enabled:
                pf.is_enabled = True
                pf.save(update_fields=["is_enabled"])
        for fid, pf in existing.items():
            if fid not in wanted and pf.is_enabled:
                pf.is_enabled = False
                pf.save(update_fields=["is_enabled"])

    def create(self, validated_data):
        feature_ids = validated_data.pop("feature_ids", None)
        package = super().create(validated_data)
        if feature_ids is not None:
            self._sync_features(package, feature_ids)
        return package

    def update(self, instance, validated_data):
        feature_ids = validated_data.pop("feature_ids", None)
        package = super().update(instance, validated_data)
        if feature_ids is not None:
            self._sync_features(package, feature_ids)
        return package


class PlatformPricingConfigSerializer(serializers.ModelSerializer):
    """GET / PATCH /billing/pricing-config/ — platform-wide pricing defaults."""

    class Meta:
        model = PlatformPricingConfig
        fields = ["id", "default_yearly_discount_percent", "updated_at"]
        read_only_fields = ["id", "updated_at"]


class PackageFeatureBulkSerializer(serializers.Serializer):
    """PUT /billing/packages/{id}/features/ — replace package feature mapping."""

    feature_ids = serializers.ListField(child=serializers.IntegerField())


class PaymentMemberOptionSerializer(serializers.ModelSerializer):
    package_name = serializers.CharField(source='member_package.name', read_only=True)

    class Meta:
        model = Member
        fields = ['id', 'full_name', 'phone_number', 'email', 'package_name']


class PaymentSerializer(serializers.ModelSerializer):
    member_name = serializers.CharField(source='member.full_name', read_only=True)
    member_phone = serializers.CharField(source='member.phone_number', read_only=True)
    member_email = serializers.CharField(source='member.email', read_only=True)
    package_name = serializers.CharField(source='member.member_package.name', read_only=True)
    payment_type_display = serializers.CharField(source='get_payment_type_display', read_only=True)
    payment_method_display = serializers.CharField(source='get_payment_method_display', read_only=True)
    payment_status_display = serializers.CharField(source='get_payment_status_display', read_only=True)
    online_transaction_status = serializers.SerializerMethodField()

    def get_online_transaction_status(self, obj):
        tx = obj.online_transactions.filter(is_deleted=False).order_by('-created_at').first()
        return tx.status if tx else None

    class Meta:
        model = Payment
        fields = [
            'id',
            'member',
            'member_name',
            'member_phone',
            'member_email',
            'package_name',
            'payment_type',
            'payment_type_display',
            'amount',
            'payment_method',
            'payment_method_display',
            'payment_status',
            'payment_status_display',
            'online_transaction_status',
            'payment_date',
            'invoice_no',
            'note',
            'is_paid',
            'is_active',
            'is_published',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'created_at',
            'updated_at',
            'member_name',
            'member_phone',
            'member_email',
            'package_name',
            'payment_type_display',
            'payment_method_display',
            'payment_status_display',
            'online_transaction_status',
        ]

    def to_internal_value(self, data):
        if isinstance(data, dict):
            mutable = dict(data)
            aliases = {
                'member_id': 'member',
                'method': 'payment_method',
                'status': 'payment_status',
                'notes': 'note',
                'invoiceNo': 'invoice_no',
            }
            for old_key, new_key in aliases.items():
                if old_key in mutable and new_key not in mutable:
                    mutable[new_key] = mutable[old_key]
            data = mutable
        return super().to_internal_value(data)

    def validate(self, attrs):
        payment_status = attrs.get('payment_status')
        is_paid = attrs.get('is_paid')

        if payment_status is not None:
            attrs['is_paid'] = payment_status == Payment.STATUS_PAID
        elif is_paid is not None:
            attrs['payment_status'] = (
                Payment.STATUS_PAID if is_paid else Payment.STATUS_DUE
            )

        return attrs


# ---------------------------------------------------------------
# Payment Gateway serializers
# ---------------------------------------------------------------

class PaymentGatewaySerializer(serializers.ModelSerializer):
    """Platform admin view/edit of a gateway row (public schema).

    `platform_credentials` is write-only so it is never sent to the frontend.
    `has_platform_credentials` is a read-only boolean indicating whether
    credentials have already been configured (without exposing the values).
    """

    platform_credentials = serializers.JSONField(write_only=True, required=False, default=dict)
    has_platform_credentials = serializers.SerializerMethodField(read_only=True)

    def get_has_platform_credentials(self, obj) -> bool:
        creds = obj.platform_credentials or {}
        return bool(creds)

    class Meta:
        model = PaymentGateway
        fields = [
            "id",
            "slug",
            "name",
            "description",
            "is_enabled_for_tenants",
            "config_schema",
            "platform_credentials",
            "has_platform_credentials",
            "is_sandbox",
            "is_default_for_subscriptions",
            "sort_order",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class TenantPaymentGatewaySerializer(serializers.ModelSerializer):
    """Tenant-level gateway configuration (tenant schema).

    `credentials` is write-only — never echoed back in responses.
    """

    credentials = serializers.JSONField(write_only=True, required=False, default=dict)

    class Meta:
        model = TenantPaymentGateway
        fields = [
            "id",
            "gateway_slug",
            "credentials",
            "is_sandbox",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class PaymentTransactionSerializer(serializers.ModelSerializer):
    """Read-only transaction audit record."""

    class Meta:
        model = PaymentTransaction
        fields = [
            "id",
            "tran_id",
            "gateway_slug",
            "amount",
            "currency",
            "status",
            "source_payment",
            "val_id",
            "validated_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class PaymentInitiateSerializer(serializers.Serializer):
    """POST /billing/payments/initiate/ request body."""

    payment_id = serializers.IntegerField()
    gateway_slug = serializers.CharField(max_length=50)


class TenantSubscriptionInvoiceSerializer(serializers.Serializer):
    """Read-only SaaS subscription invoice for the tenant dashboard."""

    id = serializers.IntegerField(read_only=True)
    package_slug = serializers.CharField(read_only=True)
    package_name = serializers.CharField(read_only=True)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    currency = serializers.CharField(read_only=True)
    tran_id = serializers.CharField(read_only=True)
    gateway_slug = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    is_trial = serializers.BooleanField(read_only=True)
    period_start = serializers.DateTimeField(read_only=True)
    period_end = serializers.DateTimeField(read_only=True)
    validated_at = serializers.DateTimeField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)


class AvailableGatewaySerializer(serializers.Serializer):
    """GET /billing/payments/available-gateways/ response shape."""

    slug = serializers.CharField()
    name = serializers.CharField()
    is_configured = serializers.BooleanField()
