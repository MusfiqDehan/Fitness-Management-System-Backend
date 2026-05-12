from rest_framework import serializers
from .models import TrainerProfile, TrainerInvitation


class InviteTrainerSerializer(serializers.Serializer):
    email = serializers.EmailField()
    inviter_id = serializers.IntegerField(required=False, allow_null=True)

    def validate_email(self, value):
        from django.db.models import Q
        if TrainerInvitation.objects.filter(
            Q(invited_email__iexact=value) & Q(accepted_at__isnull=True) & Q(is_deleted=False)
        ).exists():
            raise serializers.ValidationError('An invitation is already pending for this email.')
        if TrainerProfile.objects.filter(user__email__iexact=value).exists():
            raise serializers.ValidationError('A trainer with this email already exists.')
        return value


class SetTrainerPasswordSerializer(serializers.Serializer):
    token = serializers.CharField()
    password = serializers.CharField(min_length=8, write_only=True)
    full_name = serializers.CharField(max_length=100)
    username = serializers.SlugField(max_length=50)

    def validate_username(self, value):
        if TrainerProfile.objects.filter(username=value).exists():
            raise serializers.ValidationError('This username is already taken.')
        return value