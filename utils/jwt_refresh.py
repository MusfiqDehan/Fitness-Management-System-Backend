"""JWT refresh endpoint with Redis-backed refresh-token revocation."""

from __future__ import annotations

from rest_framework import status
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView
from django.contrib.auth import get_user_model

from utils.jwt_revocation import deny_refresh_token_raw, is_raw_refresh_token_denied
from utils.jwt_sessions import is_token_version_valid


class RevocationAwareTokenRefreshView(TokenRefreshView):
    """Reject denied or stale refresh tokens; deny rotated refresh JTIs after use."""

    def post(self, request, *args, **kwargs):
        refresh_raw = (request.data.get("refresh") or "").strip()
        if not refresh_raw:
            return Response({"detail": "refresh is required."}, status=status.HTTP_400_BAD_REQUEST)

        if is_raw_refresh_token_denied(refresh_raw):
            return Response({"detail": "Token is blacklisted"}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            refresh_token = RefreshToken(refresh_raw)
            user = get_user_model().objects.get(pk=refresh_token["user_id"])
        except (TokenError, KeyError, get_user_model().DoesNotExist):
            return Response({"detail": "Token is invalid"}, status=status.HTTP_401_UNAUTHORIZED)

        if not is_token_version_valid(refresh_token, user):
            return Response({"detail": "Token version is stale"}, status=status.HTTP_401_UNAUTHORIZED)

        response = super().post(request, *args, **kwargs)
        if response.status_code == status.HTTP_200_OK:
            deny_refresh_token_raw(refresh_raw)
        return response
