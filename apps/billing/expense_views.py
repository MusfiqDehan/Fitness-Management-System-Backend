"""Expense Manager views — categories, expenses, summary, voucher PDF."""
from __future__ import annotations

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access.permissions import HasFeatureMethodPermission
from apps.billing.expense_serializers import ExpenseCategorySerializer, ExpenseSerializer
from apps.billing.models import Expense, ExpenseCategory
from apps.billing.services.expense_voucher import render_expense_voucher_pdf
from apps.billing.services.expenses import (
    assert_category_can_be_deleted,
    build_expense_summary,
    scope_expense_queryset,
)
from apps.billing.views import PDFRenderer
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
    search_fields = [
        "title",
        "description",
        "receiver",
        "voucher_no",
        "category__name",
    ]
    ordering_fields = [
        "id",
        "expense_date",
        "amount",
        "title",
        "created_at",
        "voucher_no",
    ]
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


class ExpenseVoucherPdfAPIView(APIView):
    """Generate branded expense voucher PDF (preview inline or download)."""

    feature_key = "expenses"
    permission_classes = [IsAuthenticated, HasFeatureMethodPermission]
    renderer_classes = [PDFRenderer, JSONRenderer]

    def get(self, request, pk):
        queryset = Expense.objects.select_related("category", "branch").prefetch_related(
            "attachments"
        )
        queryset = scope_expense_queryset(queryset, request.user)
        expense = get_object_or_404(queryset, pk=pk)

        tenant_name = (
            getattr(getattr(request, "tenant", None), "name", None) or "Fithive Gym"
        )
        generated_by = getattr(request.user, "full_name", "") or getattr(
            request.user, "email", "System"
        )
        pdf_bytes = render_expense_voucher_pdf(expense, tenant_name, generated_by)
        expense.refresh_from_db(fields=["voucher_no"])
        voucher_no = expense.voucher_no or f"EXP-{expense.id:06d}"
        filename = f"expense-voucher-{voucher_no}.pdf"
        disposition = (
            "attachment" if request.query_params.get("download") == "1" else "inline"
        )

        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'{disposition}; filename="{filename}"'
        return response
