import django_filters
from django.db.models import Exists, OuterRef, Q

from .models import Member


class MemberFilter(django_filters.FilterSet):
    invitation_pending = django_filters.BooleanFilter(method="filter_invitation_pending")
    gender = django_filters.ChoiceFilter(choices=Member.GENDER_CHOICES)
    credential_linked = django_filters.ChoiceFilter(
        choices=(
            ("none", "None"),
            ("card", "Card"),
            ("fingerprint", "Fingerprint"),
            ("both", "Both"),
        ),
        method="filter_credential_linked",
    )

    class Meta:
        model = Member
        fields = [
            "is_active",
            "membership_type",
            "payment_status",
            "branch",
            "member_package",
            "gender",
        ]

    def filter_invitation_pending(self, queryset, name, value):
        pending_q = Q(invitation_token__isnull=False) & ~Q(invitation_token="")
        if value is True:
            return queryset.filter(pending_q)
        if value is False:
            return queryset.exclude(pending_q)
        return queryset

    def filter_credential_linked(self, queryset, name, value):
        """Filter by live DeviceUser linkage semantics (same as Linked column)."""
        from apps.attendance.models import DeviceUser

        linked = DeviceUser.objects.filter(
            member_id=OuterRef("pk"),
            status__in=[DeviceUser.STATUS_LINKED, DeviceUser.STATUS_PENDING_DELETE],
        )
        has_card = Exists(linked.exclude(card_number=""))
        has_fingerprint = Exists(
            linked.filter(Q(card_number="") | Q(device_uid=OuterRef("fingerprint_id")))
        )

        if value == "none":
            return queryset.filter(~Exists(linked))
        if value == "card":
            return queryset.filter(has_card).filter(~has_fingerprint)
        if value == "fingerprint":
            return queryset.filter(has_fingerprint).filter(~has_card)
        if value == "both":
            return queryset.filter(has_card).filter(has_fingerprint)
        return queryset
