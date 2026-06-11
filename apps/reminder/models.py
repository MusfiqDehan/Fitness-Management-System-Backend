from django.conf import settings
from django.db import models
from django.db.models import Q
from utils.base_model import BaseModel


class Notification(BaseModel):
    # Admin-broadcast notification types (recipient=None, visible only to admins)
    TENANT_REGISTERED = 'tenant_registered'
    TENANT_SUBSCRIBED = 'tenant_subscribed'
    MEMBER_ONBOARDED = 'member_onboarded'
    TRAINER_ONBOARDED = 'trainer_onboarded'

    # Role-specific notification types (recipient set, visible only to that user)
    WELCOME_MEMBER = 'welcome_member'
    WELCOME_TRAINER = 'welcome_trainer'
    CLASS_BOOKING_CONFIRMED = 'class_booking_confirmed'
    NEW_BOOKING_RECEIVED = 'new_booking_received'
    BOOKING_CANCELLED = 'booking_cancelled'
    PAYMENT_CONFIRMED = 'payment_confirmed'
    PAYMENT_RECEIVED = 'payment_received'
    SUBSCRIPTION_PAYMENT_CONFIRMED = 'subscription_payment_confirmed'

    NOTIFICATION_TYPE_CHOICES = [
        (TENANT_REGISTERED, 'Tenant Registered'),
        (TENANT_SUBSCRIBED, 'Tenant Subscribed'),
        (MEMBER_ONBOARDED, 'Member Onboarded'),
        (TRAINER_ONBOARDED, 'Trainer Onboarded'),
        (WELCOME_MEMBER, 'Welcome Member'),
        (WELCOME_TRAINER, 'Welcome Trainer'),
        (CLASS_BOOKING_CONFIRMED, 'Class Booking Confirmed'),
        (NEW_BOOKING_RECEIVED, 'New Booking Received'),
        (BOOKING_CANCELLED, 'Booking Cancelled'),
        (PAYMENT_CONFIRMED, 'Payment Confirmed'),
        (PAYMENT_RECEIVED, 'Payment Received'),
        (SUBSCRIPTION_PAYMENT_CONFIRMED, 'Subscription Payment Confirmed'),
    ]

    notification_type = models.CharField(
        max_length=50,
        choices=NOTIFICATION_TYPE_CHOICES,
    )
    title = models.CharField(max_length=255)
    message = models.TextField(blank=True, default='')
    actor_name = models.CharField(max_length=255, blank=True, default='')
    actor_email = models.EmailField(blank=True, default='')
    target_type = models.CharField(max_length=50, blank=True, default='')
    target_id = models.CharField(max_length=50, blank=True, default='')
    metadata = models.JSONField(null=True, blank=True)

    # Optional: if set, this notification is personal to that user only.
    # If NULL, it is a broadcast visible to all tenant admins.
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='targeted_notifications',
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(
                fields=['recipient', 'created_at'],
                name='idx_notif_recip_created',
            ),
            models.Index(
                fields=['created_at'],
                name='idx_notif_broadcast',
                condition=Q(recipient__isnull=True),
            ),
        ]

    def __str__(self):
        return f"[{self.notification_type}] {self.title}"


class NotificationRead(models.Model):
    notification = models.ForeignKey(
        Notification,
        on_delete=models.CASCADE,
        related_name='reads',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notification_reads',
    )
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('notification', 'user')

    def __str__(self):
        return f"{self.user_id} read notification {self.notification_id}"
