# accounts/views.py
from rest_framework import generics, status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import User, StudentProfile, InstructorProfile
from .serializers import (
    RegisterSerializer,
    StudentProfileSerializer,
    InstructorProfileSerializer,
    UserSerializer,
    CurrentUserSerializer,
    CurrentUserUpdateSerializer,
    EmailOrPhoneTokenObtainPairSerializer,
)


class EmailOrPhoneTokenObtainPairView(TokenObtainPairView):
    serializer_class = EmailOrPhoneTokenObtainPairSerializer


# -------------------------------
# User Registration
# -------------------------------
class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]


# -------------------------------
# Student Profile Creation
# -------------------------------
class StudentProfileCreateView(generics.CreateAPIView):
    serializer_class = StudentProfileSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        user = self.request.user

        # Ensure user is a student
        if user.role != "student":
            raise PermissionDenied("Only students can create student profile.")

        # Prevent duplicate profile
        if hasattr(user, "student_profile"):
            raise ValidationError("Student profile already exists.")

        serializer.save(user=user)


# -------------------------------
# Instructor Profile Creation
# -------------------------------
class InstructorProfileCreateView(generics.CreateAPIView):
    serializer_class = InstructorProfileSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        user = self.request.user

        # Ensure user is an instructor
        if user.role != "instructor":
            raise PermissionDenied("Only instructors can create instructor profile.")

        # Prevent duplicate profile
        if hasattr(user, "instructor_profile"):
            raise ValidationError("Instructor profile already exists.")

        serializer.save(user=user)


# -------------------------------
# Current Logged-in User
# -------------------------------
class CurrentUserAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = CurrentUserSerializer(request.user)
        return Response(serializer.data)

    def patch(self, request):
        serializer = CurrentUserUpdateSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(CurrentUserSerializer(request.user).data, status=status.HTTP_200_OK)


class InstructorListAPIView(GenericAPIView):
    queryset = User.objects.filter(role='instructor', is_active=True)
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        data = [{'id': u.id, 'name': u.email or u.phone} for u in queryset]
        return Response(data)