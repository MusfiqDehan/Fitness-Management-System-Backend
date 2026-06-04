from django.apps import AppConfig


class AttendanceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.attendance'
    label = 'attendance'
    verbose_name = 'Attendance'

    def ready(self):
        from . import signals  # noqa: F401
