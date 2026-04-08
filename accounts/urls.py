from django.urls import path
from .views import (
    RegisterView,
    StudentProfileCreateView,
    InstructorProfileCreateView,
    current_user,
)

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('student/profile/', StudentProfileCreateView.as_view(), name='student-profile'),
    path('instructor/profile/', InstructorProfileCreateView.as_view(), name='instructor-profile'),
    path('me/', current_user, name='current-user'),  # <-- this is key for dashboards
]
