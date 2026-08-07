from django.urls import path
from .views import (
    CategoryListCreateView,
    ScheduleListCreateView,
    GymClassListCreateView,
    GymClassDetailView,
    PublicGymScheduleListView,
    ContactCreateAPIView,
    PlatformSupportCreateAPIView,
)

app_name = 'quick_action'

urlpatterns = [
    path('gym-schedules/', PublicGymScheduleListView.as_view(), name='public-gym-schedules'),
    path("categories/", CategoryListCreateView.as_view()),
    path("schedules/", ScheduleListCreateView.as_view()),
    path("classes/", GymClassListCreateView.as_view()),
    path("classes/<int:pk>/", GymClassDetailView.as_view()),
    path("contact/", ContactCreateAPIView.as_view(), name="contact-create"),
    path("platform-support/", PlatformSupportCreateAPIView.as_view(), name="platform-support-create"),
]