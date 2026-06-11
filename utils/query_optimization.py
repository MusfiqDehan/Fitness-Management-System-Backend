"""Shared queryset optimizations to prevent N+1 queries on list endpoints."""

from __future__ import annotations

from django.db import DatabaseError
from django.db.models import Count, Prefetch, Q
from django_tenants.utils import get_public_schema_name, schema_context


def optimized_branch_queryset(queryset=None):
    from apps.gym_branch.models import Branch

    qs = queryset if queryset is not None else Branch.objects.all()
    return (
        qs.select_related("manager")
        .prefetch_related("facilities")
        .annotate(
            members_count=Count("members", distinct=True),
            trainers_count=Count("trainers", distinct=True),
        )
    )


def payment_online_transactions_prefetch():
    from apps.billing.models import PaymentTransaction

    return Prefetch(
        "online_transactions",
        queryset=PaymentTransaction.objects.filter(is_deleted=False).order_by(
            "-created_at"
        ),
    )


def optimized_payment_queryset(queryset=None):
    from apps.membership.models import Payment

    qs = queryset if queryset is not None else Payment.objects.all()
    return qs.select_related(
        "member",
        "member__member_package",
        "member__branch",
    ).prefetch_related(payment_online_transactions_prefetch())


def optimized_branch_shift_request_queryset(queryset=None):
    from apps.gym_branch.models import BranchShiftRequest

    qs = queryset if queryset is not None else BranchShiftRequest.objects.all()
    return qs.select_related(
        "member",
        "trainer__user",
        "from_branch",
        "to_branch",
        "reviewed_by",
    )


def prefetched_relation_count(obj, relation_name: str) -> int:
    """Return count using prefetch cache when available."""
    cache = getattr(obj, "_prefetched_objects_cache", None)
    if cache is not None and relation_name in cache:
        return len(cache[relation_name])
    return getattr(obj, relation_name).count()


def build_pending_trainer_invitation_map(emails):
    from apps.trainer.models import TrainerInvitation

    normalized = {email.lower() for email in emails if email}
    if not normalized:
        return {}

    query = Q()
    for email in normalized:
        query |= Q(invited_email__iexact=email)

    invitations = (
        TrainerInvitation.objects.filter(
            query,
            accepted_at__isnull=True,
            is_deleted=False,
        )
        .order_by("-created_at")
    )

    result = {}
    for invitation in invitations:
        key = invitation.invited_email.lower()
        if key not in result:
            result[key] = invitation
    return result


def build_tenant_admins_map(tenants):
    from apps.identity.models import User
    from apps.tenancy.serializers import TenantAdminUserSerializer

    result = {}
    for tenant in tenants:
        if tenant.schema_name == get_public_schema_name():
            result[tenant.id] = []
            continue
        try:
            with schema_context(tenant.schema_name):
                admins = User.objects.filter(role__in=["admin", "superuser"]).order_by(
                    "email", "id"
                )
                result[tenant.id] = TenantAdminUserSerializer(admins, many=True).data
        except DatabaseError:
            result[tenant.id] = []
    return result
