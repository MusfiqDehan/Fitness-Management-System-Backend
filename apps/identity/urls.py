from django.urls import path
from rest_framework_simplejwt.views import (
    TokenRefreshView,
)
from .views import (
    RegisterView,
    StudentProfileCreateView,
    InstructorProfileCreateView,
    CurrentUserAPIView,
    InstructorListAPIView,
    EmailOrPhoneTokenObtainPairView,
)

app_name = 'identity'

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', EmailOrPhoneTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('me/', CurrentUserAPIView.as_view(), name='current-user'),
    path('student/profile/', StudentProfileCreateView.as_view(), name='student-profile'),
    path('instructor/profile/', InstructorProfileCreateView.as_view(), name='instructor-profile'),
    path('instructors/', InstructorListAPIView.as_view(), name='instructor-list'),
]
