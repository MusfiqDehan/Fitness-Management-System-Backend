from django.contrib import admin

from .models import ContactQuery, EmailConfig


@admin.register(ContactQuery)
class ContactQueryAdmin(admin.ModelAdmin):
    list_display = ["full_name", "phone_number", "email", "package_name", "created_at"]
    list_filter = ["created_at"]
    search_fields = ["full_name", "phone_number", "email"]
    readonly_fields = ["created_at"]


@admin.register(EmailConfig)
class EmailConfigAdmin(admin.ModelAdmin):
    list_display = ["name", "host", "port", "host_user", "is_active", "created_at"]
    list_filter = ["is_active", "use_tls", "use_ssl"]
    search_fields = ["name", "host_user", "host"]
    readonly_fields = ["created_at", "updated_at", "created_by", "updated_by"]

