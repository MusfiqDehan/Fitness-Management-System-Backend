from django.db import models
from utils.base_model import BaseModel


# ===============================================================
# Tenant-scoped Payment Gateway configuration
# (lives in each tenant's schema)
# ===============================================================

class TenantPaymentGateway(BaseModel):
    """Per-tenant credentials for a payment gateway.

    `gateway_slug` references `tenancy.PaymentGateway.slug` in the
    public schema. No cross-schema FK is used — reference by slug only.

    `is_active` (inherited from BaseModel) acts as the tenant-level
    enable/disable toggle. SoftDeleteManager excludes deleted rows.
    """

    gateway_slug = models.CharField(
        max_length=50,
        unique=True,
        help_text="Must match a PaymentGateway.slug in the public schema.",
    )
    credentials = models.JSONField(
        default=dict,
        blank=True,
        help_text="Gateway credentials (store_id, store_password, etc.). Never expose in read responses.",
    )
    is_sandbox = models.BooleanField(
        default=True,
        help_text="When True, requests go to the gateway's sandbox/test environment.",
    )

    class Meta:
        ordering = ["gateway_slug"]

    def __str__(self):
        return f"{self.gateway_slug} ({'sandbox' if self.is_sandbox else 'live'})"


# ===============================================================
# Online Payment Transaction record
# (lives in each tenant's schema)
# ===============================================================

class PaymentTransaction(BaseModel):
    """Tracks a single online payment attempt through an external gateway.

    Linked to a `membership.Payment` via `source_payment`. The IPN/callback
    views update both this record and the linked Payment simultaneously
    inside a select_for_update() block.
    """

    STATUS_INIT = "init"
    STATUS_PENDING = "pending"
    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_INIT, "Initiated"),
        (STATUS_PENDING, "Pending"),
        (STATUS_SUCCESS, "Success"),
        (STATUS_FAILED, "Failed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    tran_id = models.CharField(max_length=100, unique=True, db_index=True)
    gateway_slug = models.CharField(max_length=50)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=10, default="BDT")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_INIT)

    # Linked membership payment — SET_NULL so deleting a Payment doesn't
    # lose the transaction audit trail.
    source_payment = models.ForeignKey(
        "membership.Payment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="online_transactions",
    )

    # Gateway response data
    gateway_response = models.JSONField(default=dict, blank=True)
    val_id = models.CharField(max_length=100, blank=True, default="")
    validated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.tran_id} [{self.status}]"

    def delete(self, using=None, keep_parents=False):
        """Financial records must not be soft-deleted — hard-delete instead."""
        super().hard_delete(using=using, keep_parents=keep_parents)
