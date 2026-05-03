from django.db import models
from django.utils import timezone
from datetime import timedelta
from django.db.models import Sum


class MemberPackage(models.Model):
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

    def __str__(self):
        return f"{self.name} - {self.price}"


class Member(models.Model):
    MEMBERSHIP_TYPE = (
        ('package', 'Package'),
        ('monthly', 'Monthly Only'),
    )

    full_name = models.CharField(max_length=150)
    phone_number = models.CharField(max_length=20, unique=True)

    membership_type = models.CharField(
        max_length=20,
        choices=MEMBERSHIP_TYPE,
        default='monthly'
    )

    member_package = models.ForeignKey(
        MemberPackage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    start_date = models.DateField(default=timezone.now)
    end_date = models.DateField(blank=True, null=True)

    # Gym Access
    card_id = models.CharField(max_length=100, unique=True, blank=True, null=True)
    fingerprint_id = models.CharField(max_length=100, unique=True, blank=True, null=True)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

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


class Payment(models.Model):
    PAYMENT_TYPE = (
        ('admission', 'Admission Fee'),
        ('package', 'Package Payment'),
        ('monthly', 'Monthly Payment'),
    )

    member = models.ForeignKey(Member, on_delete=models.CASCADE)
    payment_type = models.CharField(max_length=20, choices=PAYMENT_TYPE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)

    payment_date = models.DateTimeField(auto_now_add=True)
    note = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.member.full_name} - {self.amount}"


class Attendance(models.Model):
    ENTRY_METHOD = (
        ('card', 'Card'),
        ('fingerprint', 'Fingerprint'),
    )

    member = models.ForeignKey(Member, on_delete=models.CASCADE)
    check_in_time = models.DateTimeField(auto_now_add=True)
    check_out_time = models.DateTimeField(blank=True, null=True)
    entry_method = models.CharField(max_length=20, choices=ENTRY_METHOD)
    device_id = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        ordering = ['-check_in_time']

    def __str__(self):
        return f"{self.member.full_name} - {self.check_in_time}"