from django.urls import path

from .views import (
    BranchManagerOptionsView,
    BranchView,
    BranchShiftRequestView,
    MyBranchShiftRequestView,
    PublicBranchListView,
    PublicBranchMinimalListView,
)

app_name = 'gym_branch'

urlpatterns = [
    # Public (marketing site) endpoints
    path('public/branches/', PublicBranchListView.as_view(), name='public-branch-list'),
    path('public/branches/minimal/', PublicBranchMinimalListView.as_view(), name='public-branch-minimal'),

    # Manager assignment options
    path('manager-options/', BranchManagerOptionsView.as_view(), name='manager-options'),

    # Self-service shift requests (members / trainers)
    path('shift-requests/me/', MyBranchShiftRequestView.as_view(), name='my-shift-requests'),

    # Tenant-managed shift requests
    path('shift-requests/', BranchShiftRequestView.as_view(), name='shift-request-list'),
    path('shift-requests/<int:pk>/', BranchShiftRequestView.as_view(), name='shift-request-detail'),

    # Branch CRUD
    path('', BranchView.as_view(), name='branch-list'),
    path('<int:pk>/', BranchView.as_view(), name='branch-detail'),
]
