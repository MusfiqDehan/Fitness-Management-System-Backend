"""Serializers for tenant Expense Manager APIs."""
from __future__ import annotations

from rest_framework import serializers

from apps.billing.models import Expense, ExpenseAttachment, ExpenseCategory
from apps.billing.services.expenses import (
    assert_category_name_unique,
    replace_expense_attachments,
    validate_attachment_file_url,
)


class ExpenseCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseCategory
        fields = [
            "id",
            "name",
            "description",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_name(self, value):
        exclude_pk = self.instance.pk if self.instance else None
        return assert_category_name_unique(value, exclude_pk=exclude_pk)


class ExpenseAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseAttachment
        fields = ["id", "file_url", "file_name", "kind"]
        read_only_fields = ["id"]

    def validate_file_url(self, value):
        return validate_attachment_file_url(value)

    def validate_kind(self, value):
        allowed = {ExpenseAttachment.KIND_RECEIPT, ExpenseAttachment.KIND_ATTACHMENT}
        if value not in allowed:
            raise serializers.ValidationError("Invalid attachment kind.")
        return value


class ExpenseSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True, default=None)
    attachments = ExpenseAttachmentSerializer(many=True, required=False)

    class Meta:
        model = Expense
        fields = [
            "id",
            "title",
            "description",
            "receiver",
            "amount",
            "expense_date",
            "category",
            "category_name",
            "branch",
            "branch_name",
            "attachments",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "category_name", "branch_name", "created_at", "updated_at"]

    def validate_amount(self, value):
        if value is None or value <= 0:
            raise serializers.ValidationError("Amount must be greater than zero.")
        return value

    def validate_category(self, value):
        if value is None or getattr(value, "is_deleted", False):
            raise serializers.ValidationError("Category is required.")
        return value

    def create(self, validated_data):
        attachments_data = validated_data.pop("attachments", [])
        expense = Expense.objects.create(**validated_data)
        if attachments_data:
            replace_expense_attachments(expense, attachments_data)
        return expense

    def update(self, instance, validated_data):
        attachments_data = validated_data.pop("attachments", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if attachments_data is not None:
            replace_expense_attachments(instance, attachments_data)
        return instance
