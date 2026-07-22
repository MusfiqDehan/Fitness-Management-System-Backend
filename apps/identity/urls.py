from django.urls import path
from utils.jwt_refresh import RevocationAwareTokenRefreshView
from .views import (
    RegisterView,
    CurrentUserAPIView,
    InstructorListAPIView,
    EmailOrPhoneTokenObtainPairView,
    LogoutAPIView,
)

app_name = 'identity'

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', EmailOrPhoneTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('logout/', LogoutAPIView.as_view(), name='token_logout'),
    path('refresh/', RevocationAwareTokenRefreshView.as_view(), name='token_refresh'),
    path('me/', CurrentUserAPIView.as_view(), name='current-user'),
    path('instructors/', InstructorListAPIView.as_view(), name='instructor-list'),
]
