from django.db import models
from django.utils import timezone
from django.conf import settings
from utils.base_model import BaseModel
import secrets


# =============================================================================
# TRAINER PROFILE (extends User with role='trainer')
# =============================================================================
class TrainerProfile(BaseModel):
    """
    Trainer/Instructor profile with public-facing data.
    Uses BaseModel for soft delete, timestamps, and publish status.
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='trainer_profile'
    )

    # Public profile fields
    username = models.SlugField(
        max_length=50,
        unique=True,
        help_text='Public profile URL: /trainer/<username>'
    )
    title = models.CharField(max_length=200, blank=True, default='')
    bio = models.TextField(blank=True, default='')
    specializations = models.JSONField(default=list, blank=True)
    experience_years = models.PositiveIntegerField(default=0)

    branch = models.ForeignKey(
        'gym_branch.Branch',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='trainers',
    )
    
    # Media
    avatar = models.ImageField(upload_to='trainers/avatars/', blank=True, null=True)
    cover_photo = models.ImageField(upload_to='trainers/covers/', blank=True, null=True)
    
    # Stats (denormalized for performance)
    total_classes = models.PositiveIntegerField(default=0)
    total_members = models.PositiveIntegerField(default=0)
    average_rating = models.FloatField(default=0.0)
    total_ratings = models.PositiveIntegerField(default=0)
    
    # Highlight for landing page
    is_highlighted = models.BooleanField(default=False)
    
    # Social links
    instagram = models.URLField(blank=True, default='')
    facebook = models.URLField(blank=True, default='')
    youtube = models.URLField(blank=True, default='')
    website = models.URLField(blank=True, default='')

    class Meta:
        ordering = ['-is_highlighted', '-average_rating', 'user__full_name']

    def __str__(self):
        return f"{self.user.full_name} (@{self.username})"

    def recalc_stats(self):
        """Recalculate denormalized stats from related models."""
        from apps.trainer.models import TrainerClass, TrainerRating, ScheduleBooking
        self.total_classes = TrainerClass.objects.filter(
            trainer=self, is_deleted=False
        ).count()
        self.total_members = ScheduleBooking.objects.filter(
            schedule__trainer=self, is_deleted=False
        ).values('member').distinct().count()
        ratings = TrainerRating.objects.filter(trainer=self, is_deleted=False)
        if ratings.exists():
            self.average_rating = round(
                ratings.aggregate(models.Avg('rating'))['rating__avg'] or 0, 1
            )
            self.total_ratings = ratings.count()
        else:
            self.average_rating = 0.0
            self.total_ratings = 0
        self.save(update_fields=['total_classes', 'total_members', 'average_rating', 'total_ratings'])


# =============================================================================
# TRAINER DOCUMENT / CERTIFICATION
# =============================================================================
class TrainerDocument(BaseModel):
    """
    Documents and certifications uploaded by a trainer.
    """
    DOCUMENT_TYPES = (
        ('certification', 'Certification'),
        ('license', 'License'),
        ('award', 'Award'),
        ('other', 'Other'),
    )

    trainer = models.ForeignKey(
        TrainerProfile,
        on_delete=models.CASCADE,
        related_name='documents'
    )
    title = models.CharField(max_length=255)
    document_type = models.CharField(
        max_length=20,
        choices=DOCUMENT_TYPES,
        default='certification'
    )
    issuing_organization = models.CharField(max_length=255, blank=True, default='')
    issue_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    document_file = models.FileField(upload_to='trainers/documents/', blank=True, null=True)
    document_url = models.URLField(max_length=1000, blank=True, default='')
    description = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-issue_date', '-created_at']

    def __str__(self):
        return f"{self.title} - {self.trainer}"


# =============================================================================
# TRAINER CLASS (an offering/session type)
# =============================================================================
class TrainerClass(BaseModel):
    """
    A class or session type offered by a trainer (e.g., "Morning Yoga Flow").
    This is the template; schedules link to this.
    """
    trainer = models.ForeignKey(
        TrainerProfile,
        on_delete=models.CASCADE,
        related_name='classes'
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default='')
    category = models.CharField(max_length=100, blank=True, default='')
    difficulty_level = models.CharField(
        max_length=20,
        choices=(
            ('beginner', 'Beginner'),
            ('intermediate', 'Intermediate'),
            ('advanced', 'Advanced'),
            ('all', 'All Levels'),
        ),
        default='all'
    )
    duration_minutes = models.PositiveIntegerField(default=60)
    max_participants = models.PositiveIntegerField(default=20)
    equipment_needed = models.JSONField(default=list, blank=True)
    tags = models.JSONField(default=list, blank=True)
    
    # Pricing (if per-class fee applies)
    fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_free = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} by {self.trainer}"


# =============================================================================
# TRAINER SCHEDULE (specific datetime slots for a class)
# =============================================================================
class TrainerSchedule(BaseModel):
    """
    A scheduled session of a TrainerClass at a specific time/location.
    """
    trainer_class = models.ForeignKey(
        TrainerClass,
        on_delete=models.CASCADE,
        related_name='schedules'
    )
    trainer = models.ForeignKey(
        TrainerProfile,
        on_delete=models.CASCADE,
        related_name='schedules'
    )
    
    scheduled_date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    location = models.CharField(max_length=255, blank=True, default='')
    room_number = models.CharField(max_length=50, blank=True, default='')
    
    # Booking state
    current_participants = models.PositiveIntegerField(default=0)
    is_full = models.BooleanField(default=False)
    
    # Cancellation
    is_cancelled = models.BooleanField(default=False)
    cancellation_reason = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['scheduled_date', 'start_time']
        indexes = [
            models.Index(fields=['scheduled_date', 'start_time']),
            models.Index(fields=['trainer', 'is_published']),
        ]

    def __str__(self):
        return f"{self.trainer_class.name} on {self.scheduled_date} at {self.start_time}"

    def save(self, *args, **kwargs):
        if self.trainer_class:
            self.trainer = self.trainer_class.trainer
        self.is_full = self.current_participants >= self.trainer_class.max_participants
        super().save(*args, **kwargs)


# =============================================================================
# SCHEDULE BOOKING (member books a schedule slot)
# =============================================================================
class ScheduleBooking(BaseModel):
    """
    A booking record: a member reserves a spot in a scheduled session.
    """
    BOOKING_STATUS = (
        ('confirmed', 'Confirmed'),
        ('waitlisted', 'Waitlisted'),
        ('cancelled', 'Cancelled'),
        ('attended', 'Attended'),
        ('no_show', 'No Show'),
    )

    schedule = models.ForeignKey(
        TrainerSchedule,
        on_delete=models.CASCADE,
        related_name='bookings'
    )
    member = models.ForeignKey(
        'membership.Member',
        on_delete=models.CASCADE,
        related_name='trainer_bookings'
    )
    booked_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=20,
        choices=BOOKING_STATUS,
        default='confirmed'
    )
    check_in_time = models.DateTimeField(null=True, blank=True)
    check_out_time = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, default='')

    class Meta:
        unique_together = ['schedule', 'member']
        ordering = ['-booked_at']

    def __str__(self):
        return f"{self.member.full_name} -> {self.schedule}"


# =============================================================================
# TRAINER RATING (member rates a trainer)
# =============================================================================
class TrainerRating(BaseModel):
    """
    A member's rating and review of a trainer.
    """
    trainer = models.ForeignKey(
        TrainerProfile,
        on_delete=models.CASCADE,
        related_name='ratings'
    )
    member = models.ForeignKey(
        'membership.Member',
        on_delete=models.CASCADE,
        related_name='trainer_ratings'
    )
    rating = models.PositiveSmallIntegerField(
        help_text='1-5 star rating'
    )
    review = models.TextField(blank=True, default='')
    
    class Meta:
        unique_together = ['trainer', 'member']
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.member.full_name} rated {self.trainer} ({self.rating})"


# =============================================================================
# TRAINER INVITATION (token-based invite to become a trainer)
# =============================================================================
class TrainerInvitation(BaseModel):
    """
    Invitation sent to a prospective trainer with token-based onboarding.
    """
    invited_email = models.EmailField()
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invited_trainers'
    )
    token = models.CharField(max_length=64, unique=True)
    invitation_sent_at = models.DateTimeField(auto_now_add=True)
    invitation_expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='trainer_invitation_accepted'
    )

    class Meta:
        ordering = ['-invitation_sent_at']

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_urlsafe(48)
        if not self.invitation_expires_at:
            self.invitation_expires_at = timezone.now() + timezone.timedelta(days=7)
        super().save(*args, **kwargs)

    def is_expired(self):
        return timezone.now() > self.invitation_expires_at

    def __str__(self):
        return f"Trainer invite to {self.invited_email}"