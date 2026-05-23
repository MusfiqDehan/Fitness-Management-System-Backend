from django.urls import path
from .views import NotificationView, NotificationCountView

app_name = 'reminder'

urlpatterns = [
    path('notifications/', NotificationView.as_view(), name='notification-list'),
    path('notifications/count/', NotificationCountView.as_view(), name='notification-count'),
    path('notifications/<int:pk>/', NotificationView.as_view(), name='notification-detail'),
]