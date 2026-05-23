from django.apps import AppConfig


class ReminderConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.reminder'
    label = 'reminder'
    verbose_name = 'Reminder'
