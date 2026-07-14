from django.db import models


class GymProfile(models.Model):
    gym_name = models.CharField(max_length=150, default="")
    email = models.EmailField(blank=True, default="")
    phone = models.CharField(max_length=20, blank=True, default="")
    website = models.URLField(blank=True, default="")
    address = models.TextField(blank=True, default="")
    timezone = models.CharField(max_length=50, default="Asia/Dhaka")
    logo_url = models.URLField(max_length=1000, blank=True, default="")
    logo_width = models.PositiveIntegerField(default=120)
    logo_height = models.PositiveIntegerField(default=40)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Gym Profile"

    def __str__(self):
        return self.gym_name or "Gym Profile"


class NotificationPreferences(models.Model):
    payment_received = models.BooleanField(default=True)
    new_member_signup = models.BooleanField(default=True)
    reminder_due = models.BooleanField(default=True)
    weekly_report = models.BooleanField(default=False)
    push_notifications = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Notification Preferences"

    def __str__(self):
        return "Notification Preferences"


LANGUAGE_CHOICES = [
    ("en", "English"),
    ("bn", "বাংলা (Bengali)"),
    ("hi", "हिंदी (Hindi)"),
    ("ar", "العربية (Arabic)"),
    ("ur", "اردو (Urdu)"),
    ("zh", "中文 (Chinese)"),
    ("ja", "日本語 (Japanese)"),
    ("ko", "한국어 (Korean)"),
    ("fr", "Français (French)"),
    ("es", "Español (Spanish)"),
    ("de", "Deutsch (German)"),
    ("pt", "Português (Portuguese)"),
    ("ru", "Русский (Russian)"),
    ("tr", "Türkçe (Turkish)"),
]


class GymPreferences(models.Model):
    LANGUAGE_CHOICES = LANGUAGE_CHOICES  # module-level list shared with serializers / migrations
    CURRENCY_CHOICES = [
        ("USD", "USD — $"),
        ("EUR", "EUR — €"),
        ("GBP", "GBP — £"),
        ("BDT", "BDT — Tk."),
        ("BDTT", "BDT — ৳"),
        ("INR", "INR — ₹"),
        ("AUD", "AUD — A$"),
        ("CAD", "CAD — C$"),
        ("SGD", "SGD — S$"),
        ("AED", "AED — AED"),
        ("SAR", "SAR — SR"),
        ("OMR", "OMR — OMR"),
        ("QAR", "QAR — QR"),
        ("KWD", "KWD — KD"),
        ("BHD", "BHD — BD"),
        ("MYR", "MYR — RM"),
        ("IDR", "IDR — Rp"),
        ("CNY", "CNY — ¥"),
        ("JPY", "JPY — ¥"),
        ("TRY", "TRY — ₺"),
        ("RUB", "RUB — ₽"),
        ("ZAR", "ZAR — R"),
        ("BRL", "BRL — R$"),
    ]
    DATE_FORMAT_CHOICES = [("dmy", "DD/MM/YYYY"), ("mdy", "MM/DD/YYYY")]
    WEEK_START_CHOICES = [("sun", "Sunday"), ("mon", "Monday"), ("sat", "Saturday")]
    THEME_CHOICES = [("light", "Light"), ("dark", "Dark"), ("system", "System")]

    language = models.CharField(max_length=10, choices=LANGUAGE_CHOICES, default="en")
    currency = models.CharField(max_length=10, choices=CURRENCY_CHOICES, default="USD")
    date_format = models.CharField(max_length=20, choices=DATE_FORMAT_CHOICES, default="dmy")
    week_start = models.CharField(max_length=10, choices=WEEK_START_CHOICES, default="sat")
    theme = models.CharField(max_length=20, choices=THEME_CHOICES, default="light")
    topbar_show_date = models.BooleanField(default=False)
    topbar_show_description = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Gym Preferences"

    def __str__(self):
        return "Gym Preferences"


class ReminderTemplate(models.Model):
    TYPE_CHOICES = [
        ("payment_due", "Payment Due"),
        ("package_expiry", "Package Expiry"),
        ("overdue_notice", "Overdue Notice"),
        ("renewal", "Renewal"),
    ]
    CHANNEL_CHOICES = [
        ("sms", "SMS"),
        ("email", "Email"),
        ("both", "Both"),
    ]

    title = models.CharField(max_length=100)
    reminder_type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    channel = models.CharField(max_length=10, choices=CHANNEL_CHOICES, default="email")
    description = models.TextField(blank=True, default="")
    days_before = models.IntegerField(default=3)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["reminder_type", "title"]

    def __str__(self):
        return self.title


class Reminder(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("sent", "Sent"),
        ("failed", "Failed"),
    ]
    TYPE_CHOICES = [
        ("payment_due", "Payment Due"),
        ("package_expiry", "Package Expiry"),
        ("partial_payment", "Partial Payment"),
        ("renewal", "Renewal"),
    ]
    CHANNEL_CHOICES = [
        ("sms", "SMS"),
        ("email", "Email"),
        ("both", "Both"),
    ]

    member = models.ForeignKey(
        "membership.Member",
        on_delete=models.CASCADE,
        related_name="reminders",
    )
    reminder_type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    channel = models.CharField(max_length=10, choices=CHANNEL_CHOICES, default="email")
    due_date = models.DateField(null=True, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending")
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "reminder_type"], name="idx_reminder_status_type"),
            models.Index(fields=["status", "created_at"], name="idx_reminder_status_created"),
        ]

    def __str__(self):
        return f"{self.member} — {self.reminder_type} ({self.status})"
