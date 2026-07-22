"""Serializers for the package discount engine."""
from __future__ import annotations

from datetime import timedelta

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework import serializers

from apps.membership.models import Discount, DiscountCondition, DiscountUsage
from utils.coupon_code import validate_coupon_code_format


class DiscountConditionSerializer(serializers.ModelSerializer):
    class Meta:
        model = DiscountCondition
        fields = ["id", "field", "operator", "value", "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class DiscountSerializer(serializers.ModelSerializer):
    conditions = DiscountConditionSerializer(many=True, required=False)
    usage_count = serializers.SerializerMethodField()
    is_expired = serializers.SerializerMethodField()
    is_effectively_active = serializers.SerializerMethodField()
    # Convenience write field: sets starts_at=now and ends_at=now+minutes
    duration_minutes = serializers.IntegerField(
        required=False, allow_null=True, min_value=1, write_only=True
    )

    class Meta:
        model = Discount
        fields = [
            "id",
            "name",
            "description",
            "discount_type",
            "config",
            "application_mode",
            "coupon_code",
            "priority",
            "is_stackable",
            "stack_group",
            "scope",
            "condition_logic",
            "starts_at",
            "ends_at",
            "duration_minutes",
            "usage_limit_total",
            "usage_limit_per_member",
            "show_list_price",
            "show_percent_badge",
            "is_active",
            "is_published",
            "is_expired",
            "is_effectively_active",
            "conditions",
            "usage_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "usage_count",
            "is_expired",
            "is_effectively_active",
            "created_at",
            "updated_at",
        ]

    def get_usage_count(self, obj) -> int:
        prefetched = getattr(obj, "_usage_count", None)
        if prefetched is not None:
            return int(prefetched)
        return obj.usages.count()

    def get_is_expired(self, obj) -> bool:
        if obj.ends_at is None:
            return False
        return obj.ends_at < timezone.now()

    def get_is_effectively_active(self, obj) -> bool:
        if not obj.is_active or obj.is_deleted:
            return False
        now = timezone.now()
        if obj.starts_at and obj.starts_at > now:
            return False
        if obj.ends_at and obj.ends_at < now:
            return False
        return True

    def validate_coupon_code(self, value):
        try:
            return validate_coupon_code_format(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc

    def validate(self, attrs):
        mode = attrs.get("application_mode", getattr(self.instance, "application_mode", None))
        code = attrs.get(
            "coupon_code",
            getattr(self.instance, "coupon_code", None) if self.instance else None,
        )
        if "coupon_code" in attrs or "application_mode" in attrs:
            if mode == Discount.MODE_COUPON and not code:
                raise serializers.ValidationError(
                    {"coupon_code": "Coupon code is required for coupon application mode."}
                )
        dtype = attrs.get("discount_type", getattr(self.instance, "discount_type", None))
        config = attrs.get("config", getattr(self.instance, "config", {}) if self.instance else {})
        if not isinstance(config, dict):
            raise serializers.ValidationError({"config": "Must be an object."})
        if dtype == Discount.TYPE_PERCENTAGE and "percent" not in config and self.instance is None:
            raise serializers.ValidationError({"config": "percentage requires config.percent"})
        if dtype == Discount.TYPE_FIXED_AMOUNT and "amount" not in config and self.instance is None:
            raise serializers.ValidationError({"config": "fixed_amount requires config.amount"})
        if dtype == Discount.TYPE_FIXED_PRICE and "price" not in config and self.instance is None:
            raise serializers.ValidationError({"config": "fixed_price requires config.price"})

        duration_minutes = attrs.pop("duration_minutes", serializers.empty)
        if duration_minutes is not serializers.empty and duration_minutes is not None:
            now = timezone.now()
            attrs["starts_at"] = now
            attrs["ends_at"] = now + timedelta(minutes=int(duration_minutes))
            # Extending / restarting a timed window re-activates the discount
            attrs.setdefault("is_active", True)
        return attrs

    def _sync_conditions(self, discount: Discount, conditions_data: list | None) -> None:
        if conditions_data is None:
            return
        discount.conditions.all().delete()
        for row in conditions_data:
            DiscountCondition.objects.create(
                discount=discount,
                field=row.get("field") or "",
                operator=row.get("operator") or DiscountCondition.OP_EQ,
                value=row.get("value") if row.get("value") is not None else {},
                is_active=row.get("is_active", True),
            )

    def create(self, validated_data):
        conditions_data = validated_data.pop("conditions", None)
        discount = Discount.objects.create(**validated_data)
        self._sync_conditions(discount, conditions_data)
        return discount

    def update(self, instance, validated_data):
        conditions_data = validated_data.pop("conditions", None)
        for key, value in validated_data.items():
            setattr(instance, key, value)
        instance.save()
        self._sync_conditions(instance, conditions_data)
        return instance


class DiscountPreviewSerializer(serializers.Serializer):
    package_id = serializers.IntegerField()
    member_id = serializers.IntegerField(required=False, allow_null=True)
    coupon_code = serializers.CharField(required=False, allow_blank=True, default="")
    coverage_months = serializers.ListField(
        child=serializers.CharField(), required=False, allow_null=True
    )
    selected_addon_names = serializers.ListField(
        child=serializers.CharField(), required=False, allow_null=True
    )

    def validate_coupon_code(self, value):
        try:
            return validate_coupon_code_format(value) or ""
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc


class DiscountUsageSerializer(serializers.ModelSerializer):
    class Meta:
        model = DiscountUsage
        fields = [
            "id",
            "discount",
            "member",
            "payment",
            "coupon_code_used",
            "amount_saved",
            "meta",
            "created_at",
        ]
        read_only_fields = fields
