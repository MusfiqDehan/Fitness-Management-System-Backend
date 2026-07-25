"""Expense Manager domain services: summary, category guards, attachments."""
from __future__ import annotations

from calendar import monthrange
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.billing.models import Expense, ExpenseAttachment, ExpenseCategory
from utils.tenancy_helpers import (
    apply_branch_filter_for_tenant_admin,
    get_branch_manager_scope_ids,
)

MAX_ATTACHMENTS_PER_EXPENSE = 20


def category_name_exists(name: str, *, exclude_pk=None) -> bool:
    qs = ExpenseCategory.objects.filter(name__iexact=(name or "").strip())
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    return qs.exists()


def assert_category_name_unique(name: str, *, exclude_pk=None) -> str:
    normalized = (name or "").strip()
    if not normalized:
        raise ValidationError("Category name is required.")
    if category_name_exists(normalized, exclude_pk=exclude_pk):
        raise ValidationError("A category with this name already exists.")
    return normalized


def assert_category_can_be_deleted(category: ExpenseCategory) -> None:
    if Expense.objects.filter(category_id=category.pk).exists():
        raise ValidationError(
            {"detail": "Cannot delete a category that still has expenses."}
        )


def scope_expense_queryset(queryset, user, branch_filter_id=None):
    """Branch managers see managed branches + null-branch (company-wide) rows."""
    scope_ids = get_branch_manager_scope_ids(user)
    if scope_ids is not None:
        if not scope_ids:
            return queryset.none()
        queryset = queryset.filter(Q(branch_id__in=scope_ids) | Q(branch_id__isnull=True))
    return apply_branch_filter_for_tenant_admin(
        queryset,
        user,
        branch_filter_id,
        branch_field="branch_id",
    )


def validate_attachment_file_url(value: str) -> str:
    from django.core.exceptions import ValidationError as DjangoValidationError
    from django.core.validators import URLValidator

    normalized = (value or "").strip()
    if not normalized:
        raise ValidationError("file_url is required.")
    if normalized.startswith("/media/"):
        return normalized
    validator = URLValidator()
    try:
        validator(normalized)
    except DjangoValidationError as exc:
        raise ValidationError("Enter a valid file URL.") from exc
    return normalized


def replace_expense_attachments(expense: Expense, attachments_data: list[dict]) -> None:
    if len(attachments_data) > MAX_ATTACHMENTS_PER_EXPENSE:
        raise ValidationError(
            {
                "attachments": (
                    f"At most {MAX_ATTACHMENTS_PER_EXPENSE} attachments are allowed."
                )
            }
        )
    with transaction.atomic():
        for attachment in ExpenseAttachment.all_objects.filter(expense=expense):
            attachment.hard_delete()
        for item in attachments_data:
            ExpenseAttachment.objects.create(
                expense=expense,
                file_url=item["file_url"],
                file_name=item.get("file_name") or "",
                kind=item.get("kind") or ExpenseAttachment.KIND_ATTACHMENT,
            )


def build_expense_summary(queryset) -> dict:
    """Build summary payload from an already-scoped Expense queryset."""
    totals = queryset.aggregate(total=Sum("amount"))
    total_expenses = totals["total"] or Decimal("0.00")

    today = timezone.localdate()
    month_start = date(today.year, today.month, 1)
    last_day = monthrange(today.year, today.month)[1]
    month_end = date(today.year, today.month, last_day)
    month_totals = queryset.filter(
        expense_date__gte=month_start,
        expense_date__lte=month_end,
    ).aggregate(total=Sum("amount"))
    current_month_total = month_totals["total"] or Decimal("0.00")

    by_category_rows = (
        queryset.values("category_id", "category__name")
        .annotate(total=Sum("amount"))
        .order_by("-total", "category__name")
    )
    by_category = [
        {
            "category_id": row["category_id"],
            "name": row["category__name"],
            "total": row["total"] or Decimal("0.00"),
        }
        for row in by_category_rows
    ]
    highest_category = None
    if by_category:
        top = by_category[0]
        highest_category = {
            "id": top["category_id"],
            "name": top["name"],
            "total": top["total"],
        }

    return {
        "total_expenses": total_expenses,
        "current_month_total": current_month_total,
        "highest_category": highest_category,
        "category_count": ExpenseCategory.objects.count(),
        "by_category": by_category,
    }
