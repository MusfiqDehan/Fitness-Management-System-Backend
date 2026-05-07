from django.urls import path
from .views import (
    GymClubListAPIView,
    GymClubCreateAPIView,
    GymClubRetrieveAPIView,
    GymClubUpdateAPIView,
    GymClubDeleteAPIView,
    CategoryListCreateView,
    ScheduleListCreateView,
    GymClassListCreateView,
    GymClassDetailView,
    PublicPackageListAPIView,
    PublicPackageRetrieveAPIView,
    PublicGymScheduleListView,
    ContactCreateAPIView,
    FitHiveSupportCreateAPIView,
)

app_name = 'quick_action'

urlpatterns = [
    path('gym-schedules/', PublicGymScheduleListView.as_view(), name='public-gym-schedules'),
    path('gym-club/', GymClubListAPIView.as_view(), name='gym-club-list'),
    path('gym-club/create/', GymClubCreateAPIView.as_view(), name='gym-club-create'),
    path('gym-club/<int:pk>/', GymClubRetrieveAPIView.as_view(), name='gym-club-detail'),
    path('gym-club/<int:pk>/update/', GymClubUpdateAPIView.as_view(), name='gym-club-update'),
    path('gym-club/<int:pk>/delete/', GymClubDeleteAPIView.as_view(), name='gym-club-delete'),
    path('packages/', PublicPackageListAPIView.as_view(), name='public-packages-list'),
    path('packages/<int:pk>/', PublicPackageRetrieveAPIView.as_view(), name='public-packages-detail'),
    path("categories/", CategoryListCreateView.as_view()),
    path("schedules/", ScheduleListCreateView.as_view()),
    path("classes/", GymClassListCreateView.as_view()),
    path("classes/<int:pk>/", GymClassDetailView.as_view()),

    path("contact/", ContactCreateAPIView.as_view(), name="contact-create"),
    path("fithive-support/", FitHiveSupportCreateAPIView.as_view(), name="fithive-support-create"),
]