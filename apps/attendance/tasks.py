"""Celery tasks for attendance / device credential maintenance."""
from __future__ import annotations

from celery import shared_task


@shared_task(name="attendance.run_expired_member_credential_cleanup")
def run_expired_member_credential_cleanup_task():
    from apps.attendance.services.expired_member_credential_cleanup import (
        run_expired_member_credential_cleanup,
    )

    return run_expired_member_credential_cleanup()
