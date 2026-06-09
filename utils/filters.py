from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import BaseFilterBackend, OrderingFilter, SearchFilter

from utils.tenancy_helpers import scope_queryset_by_branch_access


class BranchScopeFilterBackend(BaseFilterBackend):
    def filter_queryset(self, request, queryset, view):
        branch_field = getattr(view, "branch_scope_field", None)
        if not branch_field:
            return queryset
        return scope_queryset_by_branch_access(
            queryset,
            request.user,
            branch_field=branch_field,
        )


class TenantAdminBranchFilterBackend(BaseFilterBackend):
    def filter_queryset(self, request, queryset, view):
        branch_field = getattr(view, "branch_scope_field", None)
        if not branch_field:
            return queryset

        branch_param = getattr(view, "branch_filter_query_param", "branch")
        return scope_queryset_by_branch_access(
            queryset,
            request.user,
            branch_field=branch_field,
            branch_filter_id=request.query_params.get(branch_param),
        )


DEFAULT_LIST_FILTER_BACKENDS = [
    DjangoFilterBackend,
    SearchFilter,
    OrderingFilter,
]

BRANCH_SCOPED_LIST_FILTER_BACKENDS = [
    BranchScopeFilterBackend,
    TenantAdminBranchFilterBackend,
    DjangoFilterBackend,
    SearchFilter,
    OrderingFilter,
]
