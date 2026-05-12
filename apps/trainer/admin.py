from django.contrib import admin
from .models import (
    TrainerProfile, TrainerDocument, TrainerClass,
    TrainerSchedule, ScheduleBooking, TrainerRating, TrainerInvitation,
)


@admin.register(TrainerProfile)
class TrainerProfileAdmin(admin.ModelAdmin):
    list_display = ['username', 'user', 'title', 'is_highlighted', 'is_published', 'average_rating']
    list_filter = ['is_highlighted', 'is_published', 'created_at']
    search_fields = ['username', 'user__email', 'user__full_name', 'title']
    readonly_fields = ['total_classes', 'total_members', 'average_rating', 'total_ratings', 'created_at', 'updated_at']


@admin.register(TrainerDocument)
class TrainerDocumentAdmin(admin.ModelAdmin):
    list_display = ['title', 'trainer', 'document_type', 'issuing_organization', 'issue_date']
    list_filter = ['document_type', 'issue_date']
    search_fields = ['title', 'trainer__user__full_name']


@admin.register(TrainerClass)
class TrainerClassAdmin(admin.ModelAdmin):
    list_display = ['name', 'trainer', 'category', 'difficulty_level', 'duration_minutes', 'max_participants']
    list_filter = ['category', 'difficulty_level', 'is_published']
    search_fields = ['name', 'trainer__user__full_name']


@admin.register(TrainerSchedule)
class TrainerScheduleAdmin(admin.ModelAdmin):
    list_display = ['trainer_class', 'scheduled_date', 'start_time', 'end_time', 'current_participants', 'is_cancelled']
    list_filter = ['scheduled_date', 'is_cancelled', 'is_published']
    search_fields = ['trainer__user__full_name', 'trainer_class__name']


@admin.register(ScheduleBooking)
class ScheduleBookingAdmin(admin.ModelAdmin):
    list_display = ['member', 'schedule', 'status', 'booked_at']
    list_filter = ['status', 'booked_at']
    search_fields = ['member__full_name', 'schedule__trainer_class__name']


@admin.register(TrainerRating)
class TrainerRatingAdmin(admin.ModelAdmin):
    list_display = ['trainer', 'member', 'rating', 'created_at']
    list_filter = ['rating', 'created_at']


@admin.register(TrainerInvitation)
class TrainerInvitationAdmin(admin.ModelAdmin):
    list_display = ['invited_email', 'invited_by', 'invitation_sent_at', 'accepted_at']
    search_fields = ['invited_email']