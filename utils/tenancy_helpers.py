from __future__ import annotations

from apps.access.models import UserRole
from apps.gym_branch.models import Branch


def is_tenant_admin_user(user) -> bool:
    return bool(
        user
        and user.is_authenticated
        and (user.is_superuser or user.is_staff or getattr(user, "role", "") == "admin")
    )


def get_branch_manager_scope_ids(user):
    """Return managed branch IDs for branch managers, otherwise None."""
    if not (user and user.is_authenticated):
        return None
    if is_tenant_admin_user(user):
        return None

    has_branch_manager_role = UserRole.objects.filter(
        user_id=user.id,
        role__slug="branch_manager",
    ).exists()
    if not has_branch_manager_role:
        return None

    return list(Branch.objects.filter(manager_id=user.id).values_list("id", flat=True))


def apply_branch_scope(queryset, user, branch_field: str = "branch_id"):
    scope_ids = get_branch_manager_scope_ids(user)
    if scope_ids is None:
        return queryset
    if not scope_ids:
        return queryset.none()
    return queryset.filter(**{f"{branch_field}__in": scope_ids})


def apply_branch_filter_for_tenant_admin(
    queryset,
    user,
    branch_id,
    branch_field: str = "branch_id",
):
    if not is_tenant_admin_user(user):
        return queryset
    if branch_id in (None, "", "all"):
        return queryset

    try:
        branch_id_int = int(branch_id)
    except (TypeError, ValueError):
        return queryset.none()

    return queryset.filter(**{branch_field: branch_id_int})


def scope_queryset_by_branch_access(
    queryset,
    user,
    branch_field: str = "branch_id",
    branch_filter_id=None,
):
    queryset = apply_branch_scope(queryset, user, branch_field=branch_field)
    return apply_branch_filter_for_tenant_admin(
        queryset,
        user,
        branch_filter_id,
        branch_field=branch_field,
    )
