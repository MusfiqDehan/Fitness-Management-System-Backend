import django_filters
from django.db.models import Q

from .models import Member


class MemberFilter(django_filters.FilterSet):
    invitation_pending = django_filters.BooleanFilter(method='filter_invitation_pending')

    class Meta:
        model = Member
        fields = [
            'is_active',
            'membership_type',
            'payment_status',
            'branch',
            'member_package',
        ]

    def filter_invitation_pending(self, queryset, name, value):
        pending_q = Q(invitation_token__isnull=False) & ~Q(invitation_token='')
        if value is True:
            return queryset.filter(pending_q)
        if value is False:
            return queryset.exclude(pending_q)
        return queryset
