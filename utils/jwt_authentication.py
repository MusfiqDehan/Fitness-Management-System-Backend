"""JWT authentication with Redis-backed access-token revocation."""

from __future__ import annotations

from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken

from utils.jwt_revocation import is_access_token_denied
from utils.jwt_sessions import is_token_version_valid


class RevocationAwareJWTAuthentication(JWTAuthentication):
    """Reject denied JTIs and stale token_version claims."""

    def get_validated_token(self, raw_token):
        validated = super().get_validated_token(raw_token)
        jti = validated.get("jti")
        if is_access_token_denied(jti):
            raise InvalidToken("Token is blacklisted")
        return validated

    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        if not is_token_version_valid(validated_token, user):
            raise InvalidToken("Token version is stale")
        return user
