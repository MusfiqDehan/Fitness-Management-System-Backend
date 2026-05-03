from django.urls import path
from .views import CheckAccessAPIView,MembersInsideAPIView

urlpatterns = [
    path('gym/check-access/', CheckAccessAPIView.as_view()),
    path('gym/members-inside/', MembersInsideAPIView.as_view()),
]