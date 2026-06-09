from django.urls import path

from .views import ContactQueryAPIView, TenantEmailConfigView

app_name = 'crm'

urlpatterns = [
    path("contact/", ContactQueryAPIView.as_view(), name="contact-query"),
    path("tenant-email-configs/", TenantEmailConfigView.as_view(), name="tenant-email-config-list"),
    path("tenant-email-configs/<int:pk>/", TenantEmailConfigView.as_view(), name="tenant-email-config-detail"),
]
