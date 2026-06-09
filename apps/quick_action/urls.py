from django.urls import path
from .views import (
    CategoryListCreateView,
    ScheduleListCreateView,
    GymClassListCreateView,
    GymClassDetailView,
    PublicGymScheduleListView,
    ContactCreateAPIView,
    FitHiveSupportCreateAPIView,
)

app_name = 'quick_action'

urlpatterns = [
    path('gym-schedules/', PublicGymScheduleListView.as_view(), name='public-gym-schedules'),
    path("categories/", CategoryListCreateView.as_view()),
    path("schedules/", ScheduleListCreateView.as_view()),
    path("classes/", GymClassListCreateView.as_view()),
    path("classes/<int:pk>/", GymClassDetailView.as_view()),
    path("contact/", ContactCreateAPIView.as_view(), name="contact-create"),
    path("fithive-support/", FitHiveSupportCreateAPIView.as_view(), name="fithive-support-create"),
]