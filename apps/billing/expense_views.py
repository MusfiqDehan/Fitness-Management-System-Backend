"""Expense Manager views — categories, expenses, summary."""
from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access.permissions import HasFeatureMethodPermission
from apps.billing.expense_serializers import ExpenseCategorySerializer, ExpenseSerializer
from apps.billing.models import Expense, ExpenseCategory
from apps.billing.services.expenses import (
    assert_category_can_be_deleted,
    build_expense_summary,
    scope_expense_queryset,
)
from utils.base_view import ModelCRUDView
from utils.list_mixins import SearchFilterSortPaginationMixin


class ExpenseCategoryAPIView(SearchFilterSortPaginationMixin, ModelCRUDView):
    feature_key = "expenses"
    queryset = ExpenseCategory.objects.all().order_by("name", "id")
    serializer_class = ExpenseCategorySerializer
    permission_classes = [HasFeatureMethodPermission]
    search_fields = ["name", "description"]
    ordering_fields = ["id", "name", "created_at"]
    ordering = ["name", "id"]

    def delete(self, request, pk=None, **kwargs):
        instance = self.get_object()
        assert_category_can_be_deleted(instance)
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ExpenseAPIView(SearchFilterSortPaginationMixin, ModelCRUDView):
    """Expense CRUD with branch visibility (null branch = company-wide)."""

    feature_key = "expenses"
    queryset = Expense.objects.select_related("category", "branch").prefetch_related(
        "attachments"
    )
    serializer_class = ExpenseSerializer
    permission_classes = [HasFeatureMethodPermission]
    filterset_fields = ["category", "branch"]
    search_fields = ["title", "description", "receiver", "category__name"]
    ordering_fields = ["id", "expense_date", "amount", "title", "created_at"]
    ordering = ["-expense_date", "-id"]

    def get_queryset(self):
        queryset = super().get_queryset()
        branch_filter = self.request.query_params.get("branch")
        queryset = scope_expense_queryset(
            queryset,
            self.request.user,
            branch_filter_id=branch_filter,
        )
        from_date = self.request.query_params.get("from_date")
        to_date = self.request.query_params.get("to_date")
        if from_date:
            queryset = queryset.filter(expense_date__gte=from_date)
        if to_date:
            queryset = queryset.filter(expense_date__lte=to_date)
        return queryset


class ExpenseSummaryAPIView(APIView):
    feature_key = "expenses"
    permission_classes = [IsAuthenticated, HasFeatureMethodPermission]

    def get(self, request):
        queryset = Expense.objects.select_related("category")
        branch_filter = request.query_params.get("branch")
        queryset = scope_expense_queryset(
            queryset,
            request.user,
            branch_filter_id=branch_filter,
        )
        return Response(build_expense_summary(queryset))
