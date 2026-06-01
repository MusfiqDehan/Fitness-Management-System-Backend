from django.urls import path
from .settings_views import (
    GymProfileAPIView,
    NotificationPreferencesAPIView,
    GymPreferencesAPIView,
    MyAccountAPIView,
    ChangePasswordAPIView,
    ReminderTemplateListAPIView,
    ReminderTemplateDetailAPIView,
    ReminderListAPIView,
    ReminderDetailAPIView,
    ReminderSendAPIView,
    ReminderStatsAPIView,
)
from .views import (
    GymClassDashboardListAPIView,
    GymClassDashboardCreateAPIView,
    GymClassDashboardRetrieveAPIView,
    GymClassDashboardUpdateAPIView,
    GymClassDashboardDeleteAPIView,
    GymClassLevelsAPIView,
    ClassBookingListAPIView,
    ClassBookingCreateAPIView,
    ClassBookingRetrieveAPIView,
    ClassBookingUpdateAPIView,
    ClassBookingDeleteAPIView,
    GymClassCategoryDashboardListAPIView,
    GymClassCategoryDashboardCreateAPIView,
    GymClassCategoryDashboardRetrieveAPIView,
    GymClassCategoryDashboardUpdateAPIView,
    GymClassCategoryDashboardDeleteAPIView,
    DashboardContactListAPIView,
    DashboardContactCreateAPIView,
    DashboardContactRetrieveAPIView,
    DashboardContactUpdateAPIView,
    DashboardContactDeleteAPIView,
    DashboardContactMarkAsReadAPIView,
    DashboardContactMarkAsRespondedAPIView,
    DashboardContactNewListAPIView,
    DashboardContactReadListAPIView,
    DashboardContactRespondedListAPIView,
    DashboardFitHiveSupportListAPIView,
    DashboardFitHiveSupportCreateAPIView,
    DashboardFitHiveSupportRetrieveAPIView,
    DashboardFitHiveSupportUpdateAPIView,
    DashboardFitHiveSupportDeleteAPIView,
    DashboardFitHiveSupportMarkAsReadAPIView,
    DashboardFitHiveSupportMarkAsRespondedAPIView,
    AttendanceDashboardListAPIView,
    AttendanceDashboardCreateAPIView,
    AttendanceDashboardRetrieveAPIView,
    AttendanceDashboardUpdateAPIView,
    AttendanceDashboardDeleteAPIView,
    FileUploadView,
    GymScheduleDashboardListAPIView,
    GymScheduleDashboardCreateAPIView,
    GymScheduleDashboardRetrieveAPIView,
    GymScheduleDashboardUpdateAPIView,
    GymScheduleDashboardDeleteAPIView,
)
from apps.identity.views import InstructorListAPIView

app_name = 'dashboard'

urlpatterns = [
    # ==== CRM related endpoints ====
    path('contacts/', DashboardContactListAPIView.as_view(), name='contact-list'),
    path('contacts/create/', DashboardContactCreateAPIView.as_view(), name='contact-create'),
    path('contacts/new/', DashboardContactNewListAPIView.as_view(), name='contact-new-list'),
    path('contacts/read/', DashboardContactReadListAPIView.as_view(), name='contact-read-list'),
    path('contacts/responded/', DashboardContactRespondedListAPIView.as_view(), name='contact-responded-list'),
    path('contacts/<int:pk>/', DashboardContactRetrieveAPIView.as_view(), name='contact-detail'),
    path('contacts/<int:pk>/update/', DashboardContactUpdateAPIView.as_view(), name='contact-update'),
    path('contacts/<int:pk>/delete/', DashboardContactDeleteAPIView.as_view(), name='contact-delete'),
    path('contacts/<int:pk>/mark-as-read/', DashboardContactMarkAsReadAPIView.as_view(), name='contact-mark-as-read'),
    path('contacts/<int:pk>/mark-as-responded/', DashboardContactMarkAsRespondedAPIView.as_view(), name='contact-mark-as-responded'),
    path('fithive-support/', DashboardFitHiveSupportListAPIView.as_view(), name='fithive-support-list'),
    path('fithive-support/create/', DashboardFitHiveSupportCreateAPIView.as_view(), name='fithive-support-create'),
    path('fithive-support/<int:pk>/', DashboardFitHiveSupportRetrieveAPIView.as_view(), name='fithive-support-detail'),
    path('fithive-support/<int:pk>/update/', DashboardFitHiveSupportUpdateAPIView.as_view(), name='fithive-support-update'),
    path('fithive-support/<int:pk>/delete/', DashboardFitHiveSupportDeleteAPIView.as_view(), name='fithive-support-delete'),
    path('fithive-support/<int:pk>/mark-as-read/', DashboardFitHiveSupportMarkAsReadAPIView.as_view(), name='fithive-support-mark-as-read'),
    path('fithive-support/<int:pk>/mark-as-responded/', DashboardFitHiveSupportMarkAsRespondedAPIView.as_view(), name='fithive-support-mark-as-responded'),
    # ==== End of CRM related endpoints ====
    
    #==== Gym Class related endpoints ====
    path('gym-classes/', GymClassDashboardListAPIView.as_view(), name='gym-class-list'),
    path('gym-classes/create/', GymClassDashboardCreateAPIView.as_view(), name='gym-class-create'),
    path('gym-classes/levels/', GymClassLevelsAPIView.as_view(), name='gym-class-levels'),
    path('gym-classes/<int:pk>/', GymClassDashboardRetrieveAPIView.as_view(), name='gym-class-detail'),
    path('gym-classes/<int:pk>/update/', GymClassDashboardUpdateAPIView.as_view(), name='gym-class-update'),
    path('gym-classes/<int:pk>/delete/', GymClassDashboardDeleteAPIView.as_view(), name='gym-class-delete'),
    path('class-bookings/', ClassBookingListAPIView.as_view(), name='class-booking-list'),
    path('class-bookings/create/', ClassBookingCreateAPIView.as_view(), name='class-booking-create'),
    path('class-bookings/<int:pk>/', ClassBookingRetrieveAPIView.as_view(), name='class-booking-detail'),
    path('class-bookings/<int:pk>/update/', ClassBookingUpdateAPIView.as_view(), name='class-booking-update'),
    path('class-bookings/<int:pk>/delete/', ClassBookingDeleteAPIView.as_view(), name='class-booking-delete'),
    path('gym-class-categories/', GymClassCategoryDashboardListAPIView.as_view(), name='gym-class-category-list'),
    path('gym-class-categories/create/', GymClassCategoryDashboardCreateAPIView.as_view(), name='gym-class-category-create'),
    path('gym-class-categories/<int:pk>/', GymClassCategoryDashboardRetrieveAPIView.as_view(), name='gym-class-category-detail'),
    path('gym-class-categories/<int:pk>/update/', GymClassCategoryDashboardUpdateAPIView.as_view(), name='gym-class-category-update'),
    path('gym-class-categories/<int:pk>/delete/', GymClassCategoryDashboardDeleteAPIView.as_view(), name='gym-class-category-delete'),
    path('gym-schedules/', GymScheduleDashboardListAPIView.as_view(), name='gym-schedule-list'),
    path('gym-schedules/create/', GymScheduleDashboardCreateAPIView.as_view(), name='gym-schedule-create'),
    path('gym-schedules/<int:pk>/', GymScheduleDashboardRetrieveAPIView.as_view(), name='gym-schedule-detail'),
    path('gym-schedules/<int:pk>/update/', GymScheduleDashboardUpdateAPIView.as_view(), name='gym-schedule-update'),
    path('gym-schedules/<int:pk>/delete/', GymScheduleDashboardDeleteAPIView.as_view(), name='gym-schedule-delete'),
    path('instructors/', InstructorListAPIView.as_view(), name='instructor-list'),
    #==== End of Gym Class related endpoints ====

    # ==== Attendance related endpoints ====
    path('attendance/', AttendanceDashboardListAPIView.as_view(), name='attendance-list'),
    path('attendance/create/', AttendanceDashboardCreateAPIView.as_view(), name='attendance-create'),
    path('attendance/<int:pk>/', AttendanceDashboardRetrieveAPIView.as_view(), name='attendance-detail'),
    path('attendance/<int:pk>/update/', AttendanceDashboardUpdateAPIView.as_view(), name='attendance-update'),
    path('attendance/<int:pk>/delete/', AttendanceDashboardDeleteAPIView.as_view(), name='attendance-delete'),
    # ==== End of Attendance related endpoints ====

    path('upload/', FileUploadView.as_view(), name='file-upload'),

    # ==== Settings endpoints ====
    path('settings/gym-profile/', GymProfileAPIView.as_view(), name='settings-gym-profile'),
    path('settings/notifications/', NotificationPreferencesAPIView.as_view(), name='settings-notifications'),
    path('settings/preferences/', GymPreferencesAPIView.as_view(), name='settings-preferences'),
    path('settings/my-account/', MyAccountAPIView.as_view(), name='settings-my-account'),
    path('settings/change-password/', ChangePasswordAPIView.as_view(), name='settings-change-password'),
    # ==== End of Settings endpoints ====

    # ==== Reminder Template endpoints ====
    path('reminder-templates/', ReminderTemplateListAPIView.as_view(), name='reminder-template-list'),
    path('reminder-templates/<int:pk>/', ReminderTemplateDetailAPIView.as_view(), name='reminder-template-detail'),
    # ==== End of Reminder Template endpoints ====

    # ==== Reminder endpoints ====
    path('reminders/', ReminderListAPIView.as_view(), name='reminder-list'),
    path('reminders/stats/', ReminderStatsAPIView.as_view(), name='reminder-stats'),
    path('reminders/<int:pk>/', ReminderDetailAPIView.as_view(), name='reminder-detail'),
    path('reminders/<int:pk>/send/', ReminderSendAPIView.as_view(), name='reminder-send'),
    # ==== End of Reminder endpoints ====
]