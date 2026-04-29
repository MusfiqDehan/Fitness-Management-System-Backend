from django.urls import path
from .views import (
    RegisterView,
    StudentProfileCreateView,
    InstructorProfileCreateView,
    CurrentUserAPIView,
    InstructorListAPIView,
)

app_name = 'accounts'

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('student/profile/', StudentProfileCreateView.as_view(), name='student-profile'),
    path('instructor/profile/', InstructorProfileCreateView.as_view(), name='instructor-profile'),
    path('me/', CurrentUserAPIView.as_view(), name='current-user'),
    path('instructors/', InstructorListAPIView.as_view(), name='instructor-list'),
]
