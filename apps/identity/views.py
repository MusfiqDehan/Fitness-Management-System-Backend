# identity/views.py
from django.db import connection
from rest_framework import generics, status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from apps.access.permissions import HasFeatureMethodPermission

from .models import User
from .serializers import (
    RegisterSerializer,
    UserSerializer,
    CurrentUserSerializer,
    CurrentUserUpdateSerializer,
    EmailOrPhoneTokenObtainPairSerializer,
)


class EmailOrPhoneTokenObtainPairView(TokenObtainPairView):
    serializer_class = EmailOrPhoneTokenObtainPairSerializer


# -------------------------------
# User Registration
# Enforces the tenant's max_users limit before creating the account.
# -------------------------------
class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]

    def create(self, request, *args, **kwargs):
        tenant = getattr(connection, 'tenant', None)
        if tenant is not None:
            current_user_count = User.objects.count()
            if current_user_count >= tenant.max_users:
                return Response(
                    {'detail': 'This gym has reached its maximum user limit.'},
                    status=status.HTTP_403_FORBIDDEN,
                )
        return super().create(request, *args, **kwargs)


# -------------------------------
# Current Logged-in User
# Includes tenant_schema so the frontend knows which tenant context
# the token was issued under.
# -------------------------------
class CurrentUserAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = CurrentUserSerializer(request.user)
        data = serializer.data
        data['tenant_schema'] = connection.schema_name
        return Response(data)

    def patch(self, request):
        serializer = CurrentUserUpdateSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        data = CurrentUserSerializer(request.user).data
        data['tenant_schema'] = connection.schema_name
        return Response(data, status=status.HTTP_200_OK)


class InstructorListAPIView(GenericAPIView):
    """
    Legacy endpoint — returns instructor users (role='instructor').
    For full trainer profiles (classes, schedules, ratings) use:
    GET /api/v1/trainer/
    """
    feature_key = 'instructors'
    queryset = User.objects.filter(role='instructor', is_active=True)
    serializer_class = UserSerializer
    permission_classes = [HasFeatureMethodPermission]

    def get(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        data = [{'id': u.id, 'name': u.email or u.phone} for u in queryset]
        return Response(data)