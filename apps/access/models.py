"""Tenant-scoped RBAC models — replicated per tenant schema.

These mirror the platform-level RBAC models in `apps.tenancy`, but
operate inside each tenant's schema, where:
  * `Role` defines a reusable bundle of permissions
  * `RolePermission` maps a Role to a feature_key + level
  * `UserRole` assigns Roles to users (members, instructors, staff)

Permission levels reuse the hierarchy from `apps.tenancy.models`:
    none(0) < view(1) < edit(2) < full(3)

`feature_key` is a free-form string (matched against `Feature.key` in
the public schema) — we cannot use a cross-schema FK.
"""
from django.db import models

from apps.tenancy.models import (
    PERMISSION_LEVEL_CHOICES,
    PERMISSION_LEVEL_VIEW,
)

class Role(models.Model):
    """A named bundle of permissions inside a tenant."""

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=120, unique=True)
    description = models.TextField(blank=True, default="")
    is_system = models.BooleanField(
        default=False,
        help_text="System roles (e.g. admin/manager) cannot be deleted.",
    )
    color = models.CharField(max_length=20, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class RolePermission(models.Model):
    """Permission level a Role grants for a specific feature_key."""

    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="permissions")
    feature_key = models.CharField(max_length=120)
    permission_level = models.CharField(
        max_length=10,
        choices=PERMISSION_LEVEL_CHOICES,
        default=PERMISSION_LEVEL_VIEW,
    )

    class Meta:
        unique_together = [("role", "feature_key")]
        indexes = [models.Index(fields=["feature_key"])]

    def __str__(self):
        return f"{self.role.name}::{self.feature_key}={self.permission_level}"


class UserRole(models.Model):
    """Assignment of a Role to a tenant user.

    We store ``user_id`` + ``user_email`` (not a FK) because the
    ``User`` model lives in the public schema and django-tenants cannot
    enforce cross-schema FK constraints. Resolution is done at runtime.
    """

    user_id = models.BigIntegerField(db_index=True)
    user_email = models.EmailField(blank=True, default="")
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="user_assignments")
    assigned_at = models.DateTimeField(auto_now_add=True)
    assigned_by_email = models.EmailField(blank=True, default="")

    class Meta:
        unique_together = [("user_id", "role")]
        indexes = [models.Index(fields=["user_email"])]

    def __str__(self):
        return f"{self.user_email or self.user_id} → {self.role.name}"

