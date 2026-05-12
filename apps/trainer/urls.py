from django.urls import path
from .views import (
    # Profile
    TrainerProfileView,
    TrainerProfileMeView,
    TrainerProfileHighlightToggleView,
    TopTrainersView,
    TrainerPublicProfileView,
    TrainerInsightsAPIView,
    # Document
    TrainerDocumentView,
    # Class
    TrainerClassView,
    TrainerClassListPublicView,
    # Schedule
    TrainerScheduleView,
    TrainerSchedulePublicView,
    # Booking
    ScheduleBookingView,
    MyBookingsView,
    BookingCheckInView,
    BookingCancelView,
    # Rating
    TrainerRatingView,
    RateTrainerView,
    MyTrainerRatingsView,
    # Invitation
    TrainerInvitationView,
    VerifyTrainerInvitationAPIView,
    CompleteTrainerRegistrationAPIView,
)


app_name = 'trainer'


# =============================================================================
# TENANT-SCOPED URLs  (api/v1/trainer/...)
# =============================================================================
urlpatterns = [
    # ---- Profile ----
    path('', TrainerProfileView.as_view(), name='trainer-list'),
    path('<int:pk>/', TrainerProfileView.as_view(), name='trainer-detail'),
    path('me/', TrainerProfileMeView.as_view(), name='trainer-me'),
    path('insights/', TrainerInsightsAPIView.as_view(), name='trainer-insights'),
    path('<int:pk>/highlight/', TrainerProfileHighlightToggleView.as_view(), name='trainer-highlight'),
    path('top/', TopTrainersView.as_view(), name='trainer-top'),
    
    # ---- Documents ----
    path('document/', TrainerDocumentView.as_view(), name='trainer-document-list'),
    path('document/<int:pk>/', TrainerDocumentView.as_view(), name='trainer-document-detail'),
    
    # ---- Classes ----
    path('class/', TrainerClassView.as_view(), name='trainer-class-list'),
    path('class/<int:pk>/', TrainerClassView.as_view(), name='trainer-class-detail'),
    path('class/public/', TrainerClassListPublicView.as_view(), name='trainer-class-public'),
    
    # ---- Schedules ----
    path('schedule/', TrainerScheduleView.as_view(), name='trainer-schedule-list'),
    path('schedule/<int:pk>/', TrainerScheduleView.as_view(), name='trainer-schedule-detail'),
    path('schedule/public/', TrainerSchedulePublicView.as_view(), name='trainer-schedule-public'),
    
    # ---- Bookings ----
    path('booking/', ScheduleBookingView.as_view(), name='trainer-booking'),
    path('booking/me/', MyBookingsView.as_view(), name='trainer-booking-me'),
    path('booking/<int:pk>/checkin/', BookingCheckInView.as_view(), name='trainer-booking-checkin'),
    path('booking/<int:pk>/cancel/', BookingCancelView.as_view(), name='trainer-booking-cancel'),
    
    # ---- Ratings ----
    path('rating/', TrainerRatingView.as_view(), name='trainer-rating-list'),
    path('rating/<int:pk>/', TrainerRatingView.as_view(), name='trainer-rating-detail'),
    path('rating/me/', MyTrainerRatingsView.as_view(), name='trainer-rating-me'),
    path('rate/', RateTrainerView.as_view(), name='trainer-rate'),
    
    # ---- Invitations ----
    path('invitation/', TrainerInvitationView.as_view(), name='trainer-invitation-list'),
    path('invitation/<int:pk>/', TrainerInvitationView.as_view(), name='trainer-invitation-detail'),

    # ---- Public profile (tenant host) ----
    path('public/profile/<slug:username>/', TrainerPublicProfileView.as_view(), name='trainer-public-profile'),

    # ---- Public invitation flow (tenant-scoped token verification) ----
    path('public/verify-invitation/', VerifyTrainerInvitationAPIView.as_view(), name='trainer-verify-invitation'),
    path('public/complete-registration/', CompleteTrainerRegistrationAPIView.as_view(), name='trainer-complete-registration'),
]


# =============================================================================
# PUBLIC URLs (no tenant scope, e.g. /trainer/register?token=X)
# These are added to PUBLIC_URLCONF in config/public_urls.py
# =============================================================================
public_urlpatterns = [
    path('trainer/public/profile/<slug:username>/', TrainerPublicProfileView.as_view(), name='trainer-public-profile'),
    path('trainer/public/verify-invitation/', VerifyTrainerInvitationAPIView.as_view(), name='trainer-verify-invitation'),
    path('trainer/public/complete-registration/', CompleteTrainerRegistrationAPIView.as_view(), name='trainer-complete-registration'),
]