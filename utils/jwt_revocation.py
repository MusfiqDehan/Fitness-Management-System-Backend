"""JWT token revocation helpers (Redis JTI denylist for access and refresh tokens)."""

from __future__ import annotations

import logging
import time  # noqa: F401 - kept for future audit extensions

from django.core.cache import cache
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken, Token

from utils.jwt_sessions import is_token_version_valid

logger = logging.getLogger(__name__)

JTI_DENY_PREFIX = "jwt:deny:jti:"


def _deny_cache_key(jti: str) -> str:
    return f"{JTI_DENY_PREFIX}{jti}"


def _deny_token_jti(token: Token) -> None:
    jti = token.get("jti")
    if not jti:
        return

    exp = token.get("exp")
    if not isinstance(exp, (int, float)):
        return

    ttl = int(exp - time.time())
    if ttl <= 0:
        return

    cache.set(_deny_cache_key(str(jti)), "1", timeout=ttl)


def is_token_jti_denied(jti: str | None) -> bool:
    """Return True when the JTI is on the denylist. Fail closed on cache errors."""
    if not jti:
        return False
    try:
        return bool(cache.get(_deny_cache_key(str(jti))))
    except Exception:
        logger.exception("JWT denylist cache lookup failed for jti=%s", jti)
        return True


def is_access_token_denied(jti: str | None) -> bool:
    return is_token_jti_denied(jti)


def is_refresh_token_denied(jti: str | None) -> bool:
    return is_token_jti_denied(jti)


def deny_access_token_raw(raw_access: str) -> None:
    if not raw_access:
        return
    try:
        token = AccessToken(raw_access)
    except TokenError:
        return
    _deny_token_jti(token)


def deny_refresh_token_raw(raw_refresh: str) -> None:
    if not raw_refresh:
        return
    try:
        token = RefreshToken(raw_refresh)
    except TokenError:
        return
    _deny_token_jti(token)


def is_raw_access_token_denied(raw_access: str) -> bool:
    if not raw_access:
        return False
    try:
        token = AccessToken(raw_access)
    except TokenError:
        return True
    return is_access_token_denied(token.get("jti"))


def is_raw_refresh_token_denied(raw_refresh: str) -> bool:
    if not raw_refresh:
        return False
    try:
        token = RefreshToken(raw_refresh)
    except TokenError:
        return True
    return is_refresh_token_denied(token.get("jti"))


def logout_tokens(
    *,
    access_raw: str | None,
    refresh_raw: str | None,
) -> None:
    """Revoke current session tokens via Redis JTI denylist."""
    if access_raw:
        deny_access_token_raw(access_raw)
    if refresh_raw:
        deny_refresh_token_raw(refresh_raw)


def access_token_from_auth_header(authorization: str | None) -> str | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    raw = authorization.split(" ", 1)[1].strip()
    return raw or None


def refresh_token_is_valid(raw_refresh: str) -> bool:
    try:
        token = RefreshToken(raw_refresh)
    except TokenError:
        return False
    if is_raw_refresh_token_denied(raw_refresh):
        return False
    from django.contrib.auth import get_user_model

    User = get_user_model()
    try:
        user = User.objects.get(pk=token["user_id"])
    except User.DoesNotExist:
        return False
    return is_token_version_valid(token, user)


def user_id_from_refresh(raw_refresh: str) -> int | None:
    try:
        token = RefreshToken(raw_refresh)
    except TokenError:
        return None
    user_id = token.payload.get("user_id")
    return int(user_id) if user_id is not None else None
