from django.contrib import admin

from django.contrib import admin
from .models import Notification, NotificationRead


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('notification_type', 'title', 'actor_name', 'actor_email', 'created_at', 'is_active')
    list_filter = ('notification_type', 'is_active', 'is_deleted')
    search_fields = ('title', 'actor_name', 'actor_email')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(NotificationRead)
class NotificationReadAdmin(admin.ModelAdmin):
    list_display = ('notification', 'user', 'read_at')
    list_filter = ('read_at',)
    search_fields = ('user__email',)
    readonly_fields = ('read_at',)

