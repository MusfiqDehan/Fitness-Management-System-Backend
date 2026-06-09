from django.conf import settings
from django.db import models

from utils.base_model import BaseModel


class Facility(models.Model):
    """A facility/amenity offered at a branch (e.g. Sauna, Pool)."""

    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name


class Branch(BaseModel):
    """A physical gym branch/location belonging to the tenant.

    Consolidates public marketing fields (image, facilities, homepage
    display) and operational fields (manager, capacity, status,
    performance metrics).
    """

    STATUS_ACTIVE = "active"
    STATUS_MAINTENANCE = "maintenance"
    STATUS_OPENING_SOON = "opening_soon"
    STATUS_CLOSED = "closed"

    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_MAINTENANCE, "Maintenance"),
        (STATUS_OPENING_SOON, "Opening Soon"),
        (STATUS_CLOSED, "Closed"),
    ]

    # ── Identity ───────────────────────────────────────────────
    name = models.CharField(max_length=150)
    code = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text="Short branch code, e.g. GLS-01.",
    )
    city = models.CharField(max_length=120, blank=True, default="")
    location = models.CharField(max_length=250, blank=True, null=True)
    address = models.TextField(blank=True, default="")
    description = models.TextField(blank=True, null=True)

    # ── Contact & operations ───────────────────────────────────
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="managed_branches",
        help_text="Tenant user who manages this branch.",
    )
    phone_number = models.CharField(max_length=20, blank=True, default="")
    email = models.EmailField(blank=True, null=True)
    operating_hours = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Display hours, e.g. '06:00 — 23:00'.",
    )
    opening_time = models.TimeField(blank=True, null=True)
    closing_time = models.TimeField(blank=True, null=True)
    weekdays_hours = models.CharField(
        max_length=50, blank=True, null=True, help_text="e.g., 6:00AM-10:00PM"
    )
    weekend_hours = models.CharField(
        max_length=50, blank=True, null=True, help_text="e.g., 6:00AM-10:00PM"
    )
    opening_date = models.DateField(blank=True, null=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE
    )

    # ── Capacity & performance ─────────────────────────────────
    capacity = models.PositiveIntegerField(default=0)
    staff_count = models.PositiveIntegerField(default=0)
    classes_per_week = models.PositiveIntegerField(default=0)
    monthly_revenue = models.DecimalField(
        max_digits=12, decimal_places=2, default=0
    )
    revenue_trend = models.FloatField(default=0.0, help_text="Percentage trend.")
    rating = models.FloatField(default=0.0)

    # ── Marketing / public site ────────────────────────────────
    facilities = models.ManyToManyField(Facility, related_name="branches", blank=True)
    image = models.ImageField(upload_to="branches/", blank=True, null=True)
    homepage_image = models.ImageField(
        upload_to="branches/homepage/", blank=True, null=True
    )
    website = models.URLField(blank=True, null=True)
    show_on_homepage = models.BooleanField(default=False)
    is_flagship = models.BooleanField(default=False)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["display_order", "name"]

    def __str__(self):
        return self.name


class BranchShiftRequest(BaseModel):
    """A request from a member or trainer to move to a different branch.

    Created by the member/trainer (from their workspace) and approved or
    rejected by a tenant admin. On approval the related member/trainer's
    ``branch`` is updated to ``to_branch``.
    """

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    member = models.ForeignKey(
        "membership.Member",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="branch_shift_requests",
    )
    trainer = models.ForeignKey(
        "trainer.TrainerProfile",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="branch_shift_requests",
    )
    from_branch = models.ForeignKey(
        Branch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="shift_requests_from",
    )
    to_branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name="shift_requests_to",
    )

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING
    )
    reason = models.TextField(blank=True, default="")
    decision_note = models.TextField(blank=True, default="")
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_branch_shifts",
    )
    reviewed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        who = self.member or self.trainer
        return f"ShiftRequest({who} → {self.to_branch})"
