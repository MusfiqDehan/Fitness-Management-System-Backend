from utils.filters import (
    BRANCH_SCOPED_LIST_FILTER_BACKENDS,
    DEFAULT_LIST_FILTER_BACKENDS,
)
from utils.pagination import StandardPagination
from utils.tenancy_helpers import scope_queryset_by_branch_access


class SearchFilterSortPaginationMixin:
    pagination_class = StandardPagination
    filter_backends = DEFAULT_LIST_FILTER_BACKENDS


class BranchScopedQuerysetMixin:
    branch_scope_field = "branch_id"
    branch_filter_query_param = "branch"

    def scope_branch_queryset(self, queryset):
        request = getattr(self, "request", None)
        if request is None:
            return queryset

        return scope_queryset_by_branch_access(
            queryset,
            request.user,
            branch_field=self.branch_scope_field,
            branch_filter_id=request.query_params.get(self.branch_filter_query_param),
        )


class BranchScopedListMixin(BranchScopedQuerysetMixin, SearchFilterSortPaginationMixin):
    filter_backends = BRANCH_SCOPED_LIST_FILTER_BACKENDS
