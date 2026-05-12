from django.db import models
from django.utils import timezone
from datetime import date, timedelta
from django.db.models import Sum
from utils.base_model import BaseModel


class MemberPackage(BaseModel):
    PACKAGE_TYPE = (
        ('monthly', 'Monthly'),
        ('3_month', '3 Months'),
        ('6_month', '6 Months'),
        ('12_month', '12 Months'),
    )

    name = models.CharField(max_length=50)
    package_type = models.CharField(max_length=20, choices=PACKAGE_TYPE)
    duration_in_days = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2)

    description = models.TextField(blank=True, default="")
    features = models.JSONField(default=list, blank=True)
    add_ons = models.JSONField(default=list, blank=True)
    display_order = models.PositiveIntegerField(default=0)
    is_highlighted = models.BooleanField(default=False)
    # is_published from BaseModel controls landing page display

    class Meta:
        ordering = ['display_order', 'name']

    def __str__(self):
        return f"{self.name} - {self.price}"


class Member(BaseModel):
    MEMBERSHIP_TYPE = (
        ('package', 'Package'),
        ('monthly', 'Monthly Only'),
    )

    GENDER_CHOICES = (
        ('male', 'Male'),
        ('female', 'Female'),
        ('other', 'Other'),
    )

    full_name = models.CharField(max_length=150)
    phone_number = models.CharField(max_length=20, unique=True)
    email = models.EmailField(blank=True, null=True)
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, blank=True, null=True)
    date_of_birth = models.DateField(null=True, blank=True)
    address = models.TextField(blank=True, default="")

    membership_type = models.CharField(
        max_length=20,
        choices=MEMBERSHIP_TYPE,
        default='monthly'
    )

    member_package = models.ForeignKey(
        MemberPackage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='members'
    )

    start_date = models.DateField(default=date.today)
    end_date = models.DateField(blank=True, null=True)

    # Gym Access
    card_id = models.CharField(max_length=100, unique=True, blank=True, null=True)
    fingerprint_id = models.CharField(max_length=100, unique=True, blank=True, null=True)

    emergency_contact_name = models.CharField(max_length=150, blank=True, default="")
    emergency_contact_phone = models.CharField(max_length=20, blank=True, default="")
    notes = models.TextField(blank=True, default="")

    # Payment tracking
    payment_method = models.CharField(max_length=50, blank=True, default="")
    payment_status = models.CharField(max_length=20, blank=True, default="unpaid")

    photo = models.ImageField(upload_to='members/photos/', blank=True, null=True)

    # ---- Invitation system ----
    invitation_token = models.CharField(max_length=64, blank=True, null=True, unique=True)
    invitation_sent_at = models.DateTimeField(blank=True, null=True)
    invitation_expires_at = models.DateTimeField(blank=True, null=True)
    invited_by = models.ForeignKey(
        'identity.User', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='invited_members',
    )

    class Meta:
        ordering = ['-created_at']

    # ----------------------------
    # PROPERTIES
    # ----------------------------

    @property
    def is_expired(self):
        return self.end_date and self.end_date < timezone.now().date()

    @property
    def is_valid(self):
        return self.is_active and not self.is_expired

    @property
    def remaining_days(self):
        if self.end_date:
            delta = self.end_date - timezone.now().date()
            return max(delta.days, 0)
        return 0

    # ----------------------------
    # SAVE LOGIC
    # ----------------------------

    def save(self, *args, **kwargs):
        is_new = self.pk is None

        # Set end_date
        if self.membership_type == 'package' and self.member_package:
            self.end_date = self.start_date + timedelta(days=self.member_package.duration_in_days)
        elif self.membership_type == 'monthly':
            self.end_date = self.start_date + timedelta(days=30)

        # Auto deactivate expired
        if self.end_date:
            self.is_active = self.end_date >= timezone.now().date()

        super().save(*args, **kwargs)

        # ----------------------------
        # AUTO CREATE PAYMENT
        # ----------------------------
        if is_new:
            # Admission fee (fixed example)
            Payment.objects.create(
                member=self,
                payment_type='admission',
                amount=500  # Change as needed
            )

            # Package or Monthly Payment
            if self.membership_type == 'package' and self.member_package:
                Payment.objects.create(
                    member=self,
                    payment_type='package',
                    amount=self.member_package.price
                )
            elif self.membership_type == 'monthly':
                Payment.objects.create(
                    member=self,
                    payment_type='monthly',
                    amount=1000  # Monthly price default
                )

    def __str__(self):
        return self.full_name


class Payment(BaseModel):
    PAYMENT_TYPE = (
        ('admission', 'Admission Fee'),
        ('package', 'Package Payment'),
        ('monthly', 'Monthly Payment'),
        ('other', 'Other'),
    )

    PAYMENT_METHOD = (
        ('bkash', 'Bkash'),
        ('nagad', 'Nagad'),
        ('card', 'Card'),
        ('cash', 'Cash'),
        ('bank_transfer', 'Bank Transfer'),
        ('other', 'Other'),
    )

    STATUS_PAID = 'paid'
    STATUS_PARTIAL = 'partial'
    STATUS_DUE = 'due'
    PAYMENT_STATUS = (
        (STATUS_PAID, 'Paid'),
        (STATUS_PARTIAL, 'Partially Paid'),
        (STATUS_DUE, 'Due'),
    )

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name='payments')
    payment_type = models.CharField(max_length=20, choices=PAYMENT_TYPE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD, default='cash')
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS, default=STATUS_DUE)
    payment_date = models.DateTimeField(default=timezone.now)
    invoice_no = models.CharField(max_length=64, blank=True, null=True, unique=True)
    note = models.TextField(blank=True, null=True)
    is_paid = models.BooleanField(default=False)

    class Meta:
        ordering = ['-payment_date']

    def save(self, *args, **kwargs):
        if self.payment_status == self.STATUS_PAID:
            self.is_paid = True
        elif self.payment_status in (self.STATUS_PARTIAL, self.STATUS_DUE):
            self.is_paid = False
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.member.full_name} - {self.amount}"


class Attendance(BaseModel):
    ENTRY_METHOD = (
        ('card', 'Card'),
        ('fingerprint', 'Fingerprint'),
    )

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name='attendances')
    check_in_time = models.DateTimeField(auto_now_add=True)
    check_out_time = models.DateTimeField(blank=True, null=True)
    entry_method = models.CharField(max_length=20, choices=ENTRY_METHOD)
    device_id = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        ordering = ['-check_in_time']

    def __str__(self):
        return f"{self.member.full_name} - {self.check_in_time.strftime('%Y-%m-%d %H:%M')}"
    device_id = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        ordering = ['-check_in_time']

    def __str__(self):
        return f"{self.member.full_name} - {self.check_in_time}"