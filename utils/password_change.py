"""Apply password updates and invalidate all active JWT sessions."""

from __future__ import annotations

from typing import Any

from django.utils import timezone

from utils.jwt_sessions import invalidate_all_user_sessions


def change_user_password(user: Any, new_password: str) -> None:
    user.set_password(new_password)
    user.password_set_at = timezone.now()
    user.save(update_fields=["password", "password_set_at"])
    invalidate_all_user_sessions(user)
