from django.conf import settings
from django.db import models
from django.utils import timezone
from datetime import date, timedelta
from django.db.models import Sum, Q
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
        indexes = [
            models.Index(
                fields=['is_active', 'is_published', 'display_order', 'name'],
                name='idx_mpkg_active_pub_order',
                condition=Q(is_deleted=False),
            ),
        ]

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
    phone_number = models.CharField(max_length=20)
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

    branch = models.ForeignKey(
        'gym_branch.Branch',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='members',
    )

    start_date = models.DateField(default=date.today)
    end_date = models.DateField(blank=True, null=True)

    # Gym Access
    card_id = models.CharField(max_length=100, unique=True, blank=True, null=True)
    fingerprint_id = models.CharField(max_length=100, unique=True, blank=True, null=True)

    emergency_contact_name = models.CharField(max_length=150, blank=True, default="")
    emergency_contact_phone = models.CharField(max_length=20, blank=True, default="")
    relationship_with_member = models.CharField(max_length=100, blank=True, default="")
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
        constraints = [
            models.UniqueConstraint(
                fields=['full_name', 'phone_number', 'date_of_birth'],
                name='uniq_member_name_phone_dob',
            ),
        ]
        indexes = [
            models.Index(
                fields=['branch', 'is_deleted', 'is_active', 'end_date'],
                name='idx_member_branch_active_end',
                condition=Q(is_deleted=False),
            ),
            models.Index(
                fields=['branch', 'is_deleted', 'created_at'],
                name='idx_member_branch_created',
                condition=Q(is_deleted=False),
            ),
        ]

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

    @staticmethod
    def default_end_date(*, membership_type, member_package, start_date):
        if not start_date:
            return None
        if membership_type == 'package' and member_package:
            return start_date + timedelta(days=member_package.duration_in_days)
        if membership_type == 'monthly':
            return start_date + timedelta(days=30)
        return None

    # ----------------------------
    # SAVE LOGIC
    # ----------------------------

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

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
        ('sslcommerz', 'SSLCommerz'),
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
    # Sorted unique YYYY-MM strings for months this payment covers.
    coverage_months = models.JSONField(default=list, blank=True)
    # Flexible fee breakdown: [{type, name, amount, ref?}].
    line_items = models.JSONField(default=list, blank=True)

    @property
    def coverage_month_count(self) -> int:
        months = self.coverage_months or []
        return len(months) if isinstance(months, list) else 0

    class Meta:
        ordering = ['-payment_date']
        indexes = [
            models.Index(
                fields=['member', 'is_deleted', 'payment_date'],
                name='idx_payment_member_date',
                condition=Q(is_deleted=False),
            ),
            models.Index(
                fields=['is_deleted', 'payment_date', 'payment_status'],
                name='idx_payment_date_status',
                condition=Q(is_deleted=False),
            ),
        ]

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
        indexes = [
            models.Index(
                fields=['member', 'check_in_time'],
                name='idx_attendance_member_checkin',
            ),
            models.Index(
                fields=['member'],
                name='idx_attendance_open_session',
                condition=Q(check_out_time__isnull=True),
            ),
        ]

    def __str__(self):
        return f"{self.member.full_name} - {self.check_in_time.strftime('%Y-%m-%d %H:%M')}"


# =============================================================================
# GYM CLASS (catalog of class types offered by the gym)
# =============================================================================

class GymClass(BaseModel):
    CLASS_TYPES = (
        ('yoga', 'Yoga'),
        ('hiit', 'HIIT'),
        ('strength', 'Strength'),
        ('cardio', 'Cardio'),
        ('pilates', 'Pilates'),
        ('zumba', 'Zumba'),
        ('karate', 'Karate'),
        ('swimming', 'Swimming'),
        ('other', 'Other'),
    )
    LEVELS = (
        ('beginner', 'Beginner'),
        ('intermediate', 'Intermediate'),
        ('advanced', 'Advanced'),
    )

    name = models.CharField(max_length=150)
    class_type = models.CharField(max_length=20, choices=CLASS_TYPES, default='other')
    level = models.CharField(max_length=20, choices=LEVELS, default='beginner')
    instructor = models.CharField(max_length=150, blank=True, default='')
    trainer_profile = models.ForeignKey(
        'trainer.TrainerProfile',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='gym_classes',
    )
    trainer_class = models.OneToOneField(
        'trainer.TrainerClass',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='gym_class',
    )
    duration_minutes = models.PositiveIntegerField(default=60)
    capacity = models.PositiveIntegerField(default=20)
    description = models.TextField(blank=True, default='')
    image_url = models.URLField(max_length=1000, blank=True, default='')

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


# =============================================================================
# GYM SCHEDULE (weekly recurring sessions for gym classes)
# =============================================================================

class GymSchedule(BaseModel):
    DAYS = (
        ('saturday', 'Saturday'),
        ('sunday', 'Sunday'),
        ('monday', 'Monday'),
        ('tuesday', 'Tuesday'),
        ('wednesday', 'Wednesday'),
        ('thursday', 'Thursday'),
        ('friday', 'Friday'),
    )
    RECURRENCE_MODES = (
        ('weekly', 'Weekly'),
        ('one_off', 'One-off'),
    )

    gym_class = models.ForeignKey(
        GymClass, on_delete=models.CASCADE, related_name='schedules', null=True, blank=True
    )
    trainer_profile = models.ForeignKey(
        'trainer.TrainerProfile',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='gym_schedules',
    )
    trainer_schedule = models.OneToOneField(
        'trainer.TrainerSchedule',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='gym_schedule',
    )
    title = models.CharField(max_length=150)
    class_type = models.CharField(max_length=20, blank=True, default='')
    instructor = models.CharField(max_length=150, blank=True, default='')
    recurrence_mode = models.CharField(max_length=10, choices=RECURRENCE_MODES, default='weekly')
    scheduled_date = models.DateField(null=True, blank=True)
    day_of_week = models.CharField(max_length=10, choices=DAYS)
    start_time = models.TimeField()
    end_time = models.TimeField()
    capacity = models.PositiveIntegerField(default=20)

    class Meta:
        ordering = ['day_of_week', 'start_time']
        indexes = [
            models.Index(
                fields=['is_deleted', 'day_of_week', 'start_time'],
                name='idx_gymsched_day_time',
                condition=Q(is_deleted=False),
            ),
        ]

    def __str__(self):
        return f"{self.title} ({self.day_of_week} {self.start_time})"


# =============================================================================
# CLASS ENROLLMENT (member enrolled in a gym class)
# =============================================================================

class ClassEnrollment(BaseModel):
    ENROLLMENT_STATUS = (
        ('active', 'Active'),
        ('removed', 'Removed'),
    )
    ENROLLMENT_SOURCE = (
        ('admin', 'Admin'),
        ('self', 'Self'),
    )

    gym_class = models.ForeignKey(
        GymClass,
        on_delete=models.CASCADE,
        related_name='enrollments',
    )
    member = models.ForeignKey(
        Member,
        on_delete=models.CASCADE,
        related_name='class_enrollments',
    )
    enrolled_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=ENROLLMENT_STATUS, default='active')
    source = models.CharField(max_length=20, choices=ENROLLMENT_SOURCE, default='admin')
    enrolled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='class_enrollments_created',
    )

    class Meta:
        ordering = ['-enrolled_at']
        indexes = [
            models.Index(
                fields=['gym_class', 'status'],
                name='idx_classenroll_class_status',
                condition=Q(is_deleted=False),
            ),
            models.Index(
                fields=['member', 'status'],
                name='idx_classenroll_member_status',
                condition=Q(is_deleted=False),
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['gym_class', 'member'],
                condition=Q(is_deleted=False),
                name='uniq_active_class_enrollment',
            ),
        ]

    def __str__(self):
        return f"{self.member.full_name} -> {self.gym_class.name}"


class Discount(BaseModel):
    """Flexible discount / coupon definition for member packages."""

    TYPE_PERCENTAGE = "percentage"
    TYPE_FIXED_AMOUNT = "fixed_amount"
    TYPE_FIXED_PRICE = "fixed_price"
    TYPE_BUY_X_GET_Y = "buy_x_get_y"
    TYPE_TIERED = "tiered"
    TYPE_FREE_ADDON = "free_addon"
    DISCOUNT_TYPES = (
        (TYPE_PERCENTAGE, "Percentage"),
        (TYPE_FIXED_AMOUNT, "Fixed Amount"),
        (TYPE_FIXED_PRICE, "Fixed Price"),
        (TYPE_BUY_X_GET_Y, "Buy X Get Y"),
        (TYPE_TIERED, "Tiered / Volume"),
        (TYPE_FREE_ADDON, "Free Add-on"),
    )

    MODE_AUTOMATIC = "automatic"
    MODE_COUPON = "coupon"
    MODE_BOTH = "both"
    APPLICATION_MODES = (
        (MODE_AUTOMATIC, "Automatic"),
        (MODE_COUPON, "Coupon"),
        (MODE_BOTH, "Both"),
    )

    LOGIC_AND = "and"
    LOGIC_OR = "or"
    CONDITION_LOGIC = (
        (LOGIC_AND, "AND"),
        (LOGIC_OR, "OR"),
    )

    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, default="")
    discount_type = models.CharField(max_length=32, choices=DISCOUNT_TYPES)
    config = models.JSONField(default=dict, blank=True)
    application_mode = models.CharField(
        max_length=16, choices=APPLICATION_MODES, default=MODE_AUTOMATIC
    )
    coupon_code = models.CharField(max_length=64, blank=True, null=True, db_index=True)
    priority = models.IntegerField(default=100)
    is_stackable = models.BooleanField(default=False)
    stack_group = models.CharField(max_length=64, blank=True, default="")
    scope = models.JSONField(default=dict, blank=True)
    condition_logic = models.CharField(
        max_length=8, choices=CONDITION_LOGIC, default=LOGIC_AND
    )
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    usage_limit_total = models.PositiveIntegerField(null=True, blank=True)
    usage_limit_per_member = models.PositiveIntegerField(null=True, blank=True)
    show_list_price = models.BooleanField(
        default=False,
        help_text="Show strikethrough original + discounted price on package listings",
    )
    show_percent_badge = models.BooleanField(
        default=False,
        help_text="Show percent-off badge on package listings (percentage discounts)",
    )

    class Meta:
        ordering = ["priority", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["coupon_code"],
                condition=Q(is_deleted=False) & ~Q(coupon_code=None) & ~Q(coupon_code=""),
                name="uniq_discount_coupon_code_active",
            ),
        ]
        indexes = [
            models.Index(
                fields=["is_active", "is_deleted", "priority"],
                name="idx_discount_active_priority",
                condition=Q(is_deleted=False),
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.discount_type})"

    def save(self, *args, **kwargs):
        if self.coupon_code is not None:
            code = str(self.coupon_code).strip()
            self.coupon_code = code.upper() if code else None
        super().save(*args, **kwargs)


class DiscountCondition(BaseModel):
    """Rule attached to a discount (field / operator / value)."""

    OP_EQ = "eq"
    OP_NEQ = "neq"
    OP_IN = "in"
    OP_GTE = "gte"
    OP_LTE = "lte"
    OP_BETWEEN = "between"
    OPERATORS = (
        (OP_EQ, "Equals"),
        (OP_NEQ, "Not equals"),
        (OP_IN, "In"),
        (OP_GTE, "Greater or equal"),
        (OP_LTE, "Less or equal"),
        (OP_BETWEEN, "Between"),
    )

    discount = models.ForeignKey(
        Discount, on_delete=models.CASCADE, related_name="conditions"
    )
    field = models.CharField(max_length=64)
    operator = models.CharField(max_length=16, choices=OPERATORS, default=OP_EQ)
    value = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.discount_id}:{self.field} {self.operator}"


class DiscountUsage(models.Model):
    """Immutable ledger of discount redemptions on payments."""

    discount = models.ForeignKey(
        Discount, on_delete=models.PROTECT, related_name="usages"
    )
    member = models.ForeignKey(
        Member,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="discount_usages",
    )
    payment = models.ForeignKey(
        Payment, on_delete=models.CASCADE, related_name="discount_usages"
    )
    coupon_code_used = models.CharField(max_length=64, blank=True, default="")
    amount_saved = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    meta = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["payment", "discount"],
                name="uniq_discount_usage_payment",
            ),
        ]
        indexes = [
            models.Index(fields=["discount", "created_at"], name="idx_dusage_discount_created"),
            models.Index(fields=["member", "discount"], name="idx_dusage_member_discount"),
        ]

    def __str__(self):
        return f"usage discount={self.discount_id} payment={self.payment_id}"

