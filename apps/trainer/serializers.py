from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import (
    TrainerProfile, TrainerDocument, TrainerClass,
    TrainerSchedule, ScheduleBooking, TrainerRating, TrainerInvitation,
)
from apps.membership.models import Member


# =============================================================================
# TRAINER PROFILE
# =============================================================================
class TrainerProfileSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.full_name', read_only=True)
    user_email = serializers.EmailField(source='user.email', read_only=True)
    user_phone = serializers.CharField(source='user.phone', read_only=True)
    is_active = serializers.BooleanField(source='user.is_active', read_only=True)
    full_name = serializers.CharField(required=False, allow_blank=True, write_only=True)
    phone = serializers.CharField(required=False, allow_blank=True, allow_null=True, write_only=True)

    def validate_phone(self, value):
        cleaned = (value or '').strip()
        if not cleaned:
            return ''

        user_model = get_user_model()
        queryset = user_model.objects.filter(phone=cleaned)
        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.user_id)
        if queryset.exists():
            raise serializers.ValidationError('Phone number already in use.')
        return cleaned

    def update(self, instance, validated_data):
        full_name = validated_data.pop('full_name', None)
        phone = validated_data.pop('phone', None)

        instance = super().update(instance, validated_data)

        user = instance.user
        changed_fields = []

        if full_name is not None:
            user.full_name = full_name.strip()
            changed_fields.append('full_name')

        if phone is not None:
            user.phone = (phone or '').strip() or None
            changed_fields.append('phone')

        if changed_fields:
            user.save(update_fields=changed_fields)

        return instance

    class Meta:
        model = TrainerProfile
        fields = [
            'id', 'user', 'user_name', 'user_email', 'user_phone', 'is_active',
            'full_name', 'phone',
            'username', 'title', 'bio', 'specializations', 'experience_years',
            'avatar', 'cover_photo',
            'total_classes', 'total_members', 'average_rating', 'total_ratings',
            'is_highlighted', 'is_published',
            'instagram', 'facebook', 'youtube', 'website',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'total_classes', 'total_members', 'average_rating', 'total_ratings',
            'created_at', 'updated_at',
        ]


class TrainerProfilePublicSerializer(serializers.ModelSerializer):
    """Public serializer for trainer's public profile page."""
    user_name = serializers.CharField(source='user.full_name', read_only=True)
    user_email = serializers.EmailField(source='user.email', read_only=True, allow_null=True)
    user_phone = serializers.CharField(source='user.phone', read_only=True, allow_null=True)
    organization_name = serializers.SerializerMethodField()
    avatar = serializers.ImageField(use_url=True, allow_null=True, required=False)
    cover_photo = serializers.ImageField(use_url=True, allow_null=True, required=False)

    def get_organization_name(self, obj):
        request = self.context.get('request')
        request_tenant = getattr(request, 'tenant', None)
        if request_tenant and getattr(request_tenant, 'name', ''):
            return request_tenant.name

        user_tenant = getattr(obj.user, 'tenant', None)
        if user_tenant and getattr(user_tenant, 'name', ''):
            return user_tenant.name

        return ''
    
    class Meta:
        model = TrainerProfile
        fields = [
            'id', 'user_name', 'user_email', 'user_phone', 'organization_name',
            'username', 'title', 'bio', 'specializations',
            'experience_years', 'avatar', 'cover_photo',
            'total_classes', 'total_members', 'average_rating', 'total_ratings',
            'instagram', 'facebook', 'youtube', 'website',
        ]


class TrainerProfileMinimalSerializer(serializers.ModelSerializer):
    """Minimal serializer for lists/dropdowns."""
    user_name = serializers.CharField(source='user.full_name', read_only=True)
    
    class Meta:
        model = TrainerProfile
        fields = ['id', 'user_name', 'username', 'title', 'avatar', 'average_rating', 'specializations']


# =============================================================================
# TRAINER DOCUMENT
# =============================================================================
class TrainerDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = TrainerDocument
        fields = [
            'id', 'trainer', 'title', 'document_type', 'issuing_organization',
            'issue_date', 'expiry_date', 'document_file', 'document_url',
            'description', 'is_active', 'is_published', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']


class TrainerDocumentPublicSerializer(serializers.ModelSerializer):
    """Public serializer for profile-visible trainer documents."""
    document_file = serializers.FileField(use_url=True, allow_null=True, required=False)

    class Meta:
        model = TrainerDocument
        fields = [
            'id', 'title', 'document_type', 'issuing_organization',
            'issue_date', 'expiry_date', 'document_file', 'document_url',
            'description',
        ]


# =============================================================================
# TRAINER CLASS
# =============================================================================
class TrainerClassSerializer(serializers.ModelSerializer):
    trainer_name = serializers.CharField(source='trainer.user.full_name', read_only=True)
    
    class Meta:
        model = TrainerClass
        fields = [
            'id', 'trainer', 'trainer_name', 'name', 'description', 'category',
            'difficulty_level', 'duration_minutes', 'max_participants',
            'equipment_needed', 'tags', 'fee', 'is_free',
            'is_active', 'is_published', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']


class TrainerClassPublicSerializer(serializers.ModelSerializer):
    """Public serializer for browsing available classes."""
    trainer_name = serializers.CharField(source='trainer.user.full_name', read_only=True)
    trainer_username = serializers.CharField(source='trainer.username', read_only=True)
    trainer_avatar = serializers.ImageField(source='trainer.avatar', read_only=True)
    
    class Meta:
        model = TrainerClass
        fields = [
            'id', 'trainer', 'trainer_name', 'trainer_username', 'trainer_avatar',
            'name', 'description', 'category', 'difficulty_level',
            'duration_minutes', 'max_participants', 'equipment_needed', 'tags',
            'fee', 'is_free', 'is_published',
        ]


# =============================================================================
# TRAINER SCHEDULE
# =============================================================================
class TrainerScheduleSerializer(serializers.ModelSerializer):
    trainer_class_name = serializers.CharField(source='trainer_class.name', read_only=True)
    trainer_name = serializers.CharField(source='trainer.user.full_name', read_only=True)
    available_spots = serializers.SerializerMethodField()
    
    class Meta:
        model = TrainerSchedule
        fields = [
            'id', 'trainer_class', 'trainer_class_name', 'trainer', 'trainer_name',
            'scheduled_date', 'start_time', 'end_time', 'location', 'room_number',
            'current_participants', 'available_spots', 'is_full', 'is_cancelled',
            'cancellation_reason', 'is_active', 'is_published', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at', 'is_full']

    def get_available_spots(self, obj):
        return max(0, obj.trainer_class.max_participants - obj.current_participants)


class TrainerSchedulePublicSerializer(TrainerScheduleSerializer):
    """Public serializer for members booking schedules."""
    class Meta(TrainerScheduleSerializer.Meta):
        fields = [
            'id', 'trainer_class', 'trainer_class_name', 'trainer', 'trainer_name',
            'scheduled_date', 'start_time', 'end_time', 'location', 'room_number',
            'available_spots', 'is_full', 'is_published',
        ]


# =============================================================================
# SCHEDULE BOOKING
# =============================================================================
class ScheduleBookingSerializer(serializers.ModelSerializer):
    member_name = serializers.CharField(source='member.full_name', read_only=True)
    schedule_info = serializers.SerializerMethodField()
    
    class Meta:
        model = ScheduleBooking
        fields = [
            'id', 'schedule', 'member', 'member_name', 'booked_at', 'status',
            'check_in_time', 'check_out_time', 'notes', 'schedule_info',
            'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = ['booked_at', 'created_at', 'updated_at']

    def get_schedule_info(self, obj):
        return {
            'class_name': obj.schedule.trainer_class.name,
            'date': obj.schedule.scheduled_date,
            'start_time': obj.schedule.start_time,
            'end_time': obj.schedule.end_time,
            'location': obj.schedule.location,
            'trainer_id': obj.schedule.trainer_id,
            'trainer_name': obj.schedule.trainer.user.full_name or obj.schedule.trainer.user.email,
        }


class ScheduleBookingCreateSerializer(serializers.Serializer):
    schedule_id = serializers.IntegerField()
    
    def validate_schedule_id(self, value):
        try:
            schedule = TrainerSchedule.objects.get(pk=value, is_deleted=False, is_cancelled=False)
        except TrainerSchedule.DoesNotExist:
            raise serializers.ValidationError('Schedule not found or unavailable.')
        if schedule.is_full:
            raise serializers.ValidationError('This schedule is fully booked.')
        return value

    def create(self, validated_data):
        try:
            member = self.context['request'].user.member
        except Exception:
            raise serializers.ValidationError('Member profile not found for this account.')
        schedule = TrainerSchedule.objects.get(pk=validated_data['schedule_id'])
        
        # Check for existing booking
        if ScheduleBooking.objects.filter(schedule=schedule, member=member, is_deleted=False).exists():
            raise serializers.ValidationError('You have already booked this schedule.')
        
        booking = ScheduleBooking.objects.create(
            schedule=schedule,
            member=member,
            status='confirmed'
        )
        
        # Update participant count
        schedule.current_participants += 1
        schedule.save(update_fields=['current_participants'])
        
        return booking


# =============================================================================
# TRAINER RATING
# =============================================================================
class TrainerRatingSerializer(serializers.ModelSerializer):
    member_name = serializers.CharField(source='member.full_name', read_only=True)
    
    class Meta:
        model = TrainerRating
        fields = [
            'id', 'trainer', 'member', 'member_name', 'rating', 'review',
            'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']

    def validate_rating(self, value):
        if not 1 <= value <= 5:
            raise serializers.ValidationError('Rating must be between 1 and 5.')
        return value

    def validate(self, attrs):
        # Prevent duplicate rating by same member for same trainer
        if not self.instance:
            trainer = attrs.get('trainer')
            member = attrs.get('member')
            if TrainerRating.objects.filter(trainer=trainer, member=member, is_deleted=False).exists():
                raise serializers.ValidationError('You have already rated this trainer.')
        return attrs


class TrainerRatingCreateSerializer(serializers.Serializer):
    trainer_id = serializers.IntegerField()
    rating = serializers.IntegerField(min_value=1, max_value=5)
    review = serializers.CharField(required=False, allow_blank=True, default='')

    def validate_trainer_id(self, value):
        try:
            TrainerProfile.objects.get(pk=value, is_deleted=False)
        except TrainerProfile.DoesNotExist:
            raise serializers.ValidationError('Trainer not found.')
        return value

    def validate(self, attrs):
        try:
            member = self.context['request'].user.member
        except Exception:
            raise serializers.ValidationError('Member profile not found for this account.')
        trainer_id = attrs.get('trainer_id')
        if trainer_id and TrainerRating.objects.filter(
            trainer_id=trainer_id, member=member, is_deleted=False
        ).exists():
            raise serializers.ValidationError('You have already submitted a review for this trainer.')
        return attrs

    def create(self, validated_data):
        try:
            member = self.context['request'].user.member
        except Exception:
            raise serializers.ValidationError('Member profile not found for this account.')
        trainer = TrainerProfile.objects.get(pk=validated_data['trainer_id'])
        rating = TrainerRating.objects.create(
            trainer=trainer,
            member=member,
            rating=validated_data['rating'],
            review=validated_data.get('review', '')
        )
        trainer.recalc_stats()
        return rating


# =============================================================================
# TRAINER INVITATION
# =============================================================================
class TrainerInvitationSerializer(serializers.ModelSerializer):
    invited_by_name = serializers.CharField(source='invited_by.full_name', read_only=True)
    is_expired = serializers.BooleanField(read_only=True)
    
    class Meta:
        model = TrainerInvitation
        fields = [
            'id', 'invited_email', 'invited_by', 'invited_by_name',
            'token', 'invitation_sent_at', 'invitation_expires_at',
            'accepted_at', 'is_expired', 'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'token', 'invitation_sent_at', 'accepted_at', 'is_expired',
            'created_at', 'updated_at',
        ]


class TrainerInvitationCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    inviter_id = serializers.IntegerField(required=False, allow_null=True)

    def validate_email(self, value):
        if TrainerInvitation.objects.filter(
            invited_email__iexact=value,
            accepted_at__isnull=True,
            is_deleted=False
        ).exists():
            raise serializers.ValidationError('An invitation has already been sent to this email.')
        if TrainerProfile.objects.filter(user__email__iexact=value).exists():
            raise serializers.ValidationError('A trainer with this email already exists.')
        return value

    def create(self, validated_data):
        from django.utils import timezone
        inviter = None
        if validated_data.get('inviter_id'):
            from apps.identity.models import User
            try:
                inviter = User.objects.get(pk=validated_data['inviter_id'])
            except User.DoesNotExist:
                pass
        
        invitation = TrainerInvitation.objects.create(
            invited_email=validated_data['email'],
            invited_by=inviter,
            invitation_expires_at=timezone.now() + timezone.timedelta(days=7)
        )
        return invitation


class VerifyTrainerInvitationSerializer(serializers.Serializer):
    token = serializers.CharField()

    def validate_token(self, value):
        try:
            invitation = TrainerInvitation.objects.get(token=value, is_deleted=False)
        except TrainerInvitation.DoesNotExist:
            raise serializers.ValidationError('Invalid invitation token.')
        if invitation.accepted_at:
            raise serializers.ValidationError('This invitation has already been accepted.')
        if invitation.is_expired():
            raise serializers.ValidationError('This invitation has expired.')
        return value


class CompleteTrainerRegistrationSerializer(serializers.Serializer):
    token = serializers.CharField()
    password = serializers.CharField(min_length=8, write_only=True)
    full_name = serializers.CharField(max_length=100)
    username = serializers.SlugField(max_length=50)
    title = serializers.CharField(max_length=200, required=False, allow_blank=True, default='')
    phone = serializers.CharField(max_length=15, required=False, allow_blank=True, default='')

    def validate_username(self, value):
        if TrainerProfile.objects.filter(username=value).exists():
            raise serializers.ValidationError('This username is already taken.')
        return value

    def validate_password(self, value):
        import re
        if len(value) < 8:
            raise serializers.ValidationError('Password must be at least 8 characters.')
        if not re.search(r'[a-z]', value):
            raise serializers.ValidationError('Password must contain a lowercase letter.')
        if not re.search(r'[A-Z]', value):
            raise serializers.ValidationError('Password must contain an uppercase letter.')
        if not re.search(r'\d', value):
            raise serializers.ValidationError('Password must contain a number.')
        return value

    def create(self, validated_data):
        from django.db import transaction
        from django.utils import timezone
        from apps.identity.models import User
        
        invitation = TrainerInvitation.objects.get(token=validated_data['token'])
        
        with transaction.atomic():
            # Create user
            user = User.objects.create(
                email=invitation.invited_email,
                full_name=validated_data['full_name'],
                phone=validated_data.get('phone') or None,
                role='trainer',
                email_verified=True,
                password_set_at=timezone.now(),
            )
            user.set_password(validated_data['password'])
            user.save()
            
            # Create trainer profile
            profile = TrainerProfile.objects.create(
                user=user,
                username=validated_data['username'],
                title=validated_data.get('title', ''),
            )
            
            # Mark invitation as accepted
            invitation.accepted_at = timezone.now()
            invitation.accepted_by = user
            invitation.save(update_fields=['accepted_at', 'accepted_by'])
            
            return profile