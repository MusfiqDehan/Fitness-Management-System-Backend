"""Reusable helpers for enforcing tenant subscription limits.

Limits live on the active tenant (``connection.tenant``). A limit value of
``0`` (or ``None``) means *unlimited*.
"""
from django.db import connection


def _backfill_branch_limit_from_package(tenant, current_limit):
    """Backfill stale tenant branch cap from active package when needed.

    Older onboarding flows stored default caps (e.g. max_branches=1) even for
    higher plans like Growth. This refreshes that one field on demand so limit
    checks reflect the subscribed package.
    """
    if tenant is None:
        return current_limit
    if int(current_limit or 0) != 1:
        return current_limit

    plan_slug = str(getattr(tenant, "plan", "") or "").strip().lower()
    if not plan_slug:
        return current_limit

    try:
        from apps.tenancy.models import PlatformPackage

        pkg = PlatformPackage.objects.filter(slug=plan_slug, is_active=True).first()
    except Exception:
        return current_limit

    if pkg is None:
        return current_limit

    package_limit = int(getattr(pkg, "max_branches", 0) or 0)
    if package_limit <= int(current_limit or 0):
        return current_limit

    tenant.max_branches = package_limit
    try:
        tenant.save(update_fields=["max_branches", "updated_at"])
    except Exception:
        # Read-path resiliency: do not fail capacity checks on backfill errors.
        return current_limit
    return package_limit


def get_tenant_limit(limit_attr):
    """Return the configured limit for the active tenant, or 0 (unlimited)."""
    tenant = getattr(connection, "tenant", None)
    if tenant is None:
        return 0

    limit = getattr(tenant, limit_attr, 0) or 0
    if limit_attr == "max_branches":
        limit = _backfill_branch_limit_from_package(tenant, limit)
    return limit


def _limit_exceeded_payload(*, detail, limit_type, limit, current):
    """Standard payload returned when a tenant plan limit is exceeded."""
    return {
        "detail": detail,
        "code": "LIMIT_EXCEEDED",
        "limit_type": limit_type,
        "limit": limit,
        "current": current,
        "upgrade_action": "upgrade_plan",
        "upgrade_path": "/settings",
    }


def total_capacity_exceeded(queryset, limit_attr, *, limit_type):
    """Check tenant-wide capacity for a queryset.

    Returns a standard limit payload dict or ``None``.
    """
    limit = get_tenant_limit(limit_attr)
    if not limit:
        return None

    current = queryset.count()
    if current >= limit:
        return _limit_exceeded_payload(
            detail=(
                "You have reached the maximum number allowed by your current "
                "plan. Please upgrade to add more."
            ),
            limit_type=limit_type,
            limit=limit,
            current=current,
        )
    return None


def branch_capacity_exceeded(queryset, branch_id, limit_attr, *, limit_type=None):
    """Check whether adding one row to ``branch_id`` would exceed the limit.

    ``queryset`` must be filterable by ``branch_id``. Returns a dict describing
    the breach (suitable for a 403 body) or ``None`` when within limits.
    """
    limit = get_tenant_limit(limit_attr)
    if not limit or branch_id is None:
        return None

    current = queryset.filter(branch_id=branch_id).count()
    if current >= limit:
        return _limit_exceeded_payload(
            detail=(
                "You have reached the maximum number allowed by your current "
                "plan for this branch. Please upgrade to add more."
            ),
            limit_type=limit_type or limit_attr,
            limit=limit,
            current=current,
        )
    return None
