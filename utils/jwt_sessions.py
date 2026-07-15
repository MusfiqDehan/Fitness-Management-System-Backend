"""JWT session claims — token_version invalidates all sessions on password change."""

from __future__ import annotations

from typing import Any

from rest_framework_simplejwt.tokens import Token

TOKEN_VERSION_CLAIM = "token_version"


def embed_token_version(token: Token, user: Any) -> None:
    token[TOKEN_VERSION_CLAIM] = getattr(user, "token_version", 1)


def claim_token_version(token: Token | dict[str, Any]) -> int:
    if hasattr(token, "get"):
        raw = token.get(TOKEN_VERSION_CLAIM, 1)
    else:
        raw = 1
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def is_token_version_valid(token: Token | dict[str, Any], user: Any) -> bool:
    return claim_token_version(token) == getattr(user, "token_version", 1)


def invalidate_all_user_sessions(user: Any) -> int:
    """Bump token_version so every outstanding JWT for this user is rejected."""
    current = getattr(user, "token_version", 1) or 1
    user.token_version = current + 1
    user.save(update_fields=["token_version"])
    return user.token_version
