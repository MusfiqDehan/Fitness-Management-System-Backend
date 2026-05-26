from django.urls import path

from .views import ContactQueryAPIView

app_name = 'crm'

urlpatterns = [
    path("contact/", ContactQueryAPIView.as_view(), name="contact-query"),
]
