from django.urls import path

from .views import ContactQueryAPIView, EmailConfigView

app_name = "crm_public"

urlpatterns = [
    path("contact/", ContactQueryAPIView.as_view(), name="contact-query"),
    # Platform-admin email configuration management
    # Actions dispatched via POST /email-configs/<pk>/?action=activate|deactivate|restore
    path("email-configs/", EmailConfigView.as_view(), name="email-config-list"),
    path("email-configs/<int:pk>/", EmailConfigView.as_view(), name="email-config-detail"),
]
