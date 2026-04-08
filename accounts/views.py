# accounts/views.py
from rest_framework import generics
from rest_framework.viewsets import ReadOnlyModelViewSet
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, ValidationError

from .models import User, StudentProfile, InstructorProfile
from .serializers import (
    RegisterSerializer,
    StudentProfileSerializer,
    InstructorProfileSerializer,
    UserSerializer
)


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
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def current_user(request):
    """
    Returns the currently logged-in user with role and full_name (from profile if exists)
    """
    user = request.user

    # Get full name from profile if exists
    full_name = None
    if user.role == 'student' and hasattr(user, 'student_profile'):
        full_name = user.student_profile.full_name
    elif user.role == 'instructor' and hasattr(user, 'instructor_profile'):
        full_name = user.instructor_profile.full_name
    elif user.role in ['admin', 'staff', 'superuser']:
        full_name = user.email

    return Response({
        "id": user.id,
        "email": user.email,
        "phone": user.phone,
        "role": user.role,
        "full_name": full_name or user.email
    })

class InstructorViewSet(ReadOnlyModelViewSet):
    queryset = User.objects.filter(role='instructor', is_active=True)
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        data = [{'id': u.id, 'name': u.email or u.phone} for u in queryset]
        return Response(data)