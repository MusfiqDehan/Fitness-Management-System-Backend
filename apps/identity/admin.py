from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, StudentProfile, InstructorProfile

class UserAdmin(BaseUserAdmin):
    list_display = ('email', 'phone', 'tenant', 'role', 'is_staff', 'is_superuser', 'is_active', 'email_verified', 'created_at')
    list_filter = ('tenant', 'role', 'is_staff', 'is_superuser', 'is_active', 'email_verified')

    # Remove non-editable 'created_at' from fieldsets
    fieldsets = (
        (None, {'fields': ('email', 'phone', 'password', 'full_name', 'tenant')}),
        ('Permissions', {'fields': ('role', 'is_staff', 'is_superuser', 'is_active', 'email_verified', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'password_set_at')}),  # Removed 'created_at'
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'phone', 'full_name', 'tenant', 'role', 'password1', 'password2', 'is_staff', 'is_superuser', 'is_active', 'email_verified')}
        ),
    )

    search_fields = ('email', 'phone')
    ordering = ('email',)
    filter_horizontal = ('groups', 'user_permissions')


class StudentProfileAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'user', 'age', 'weight', 'height', 'emergency_contact')
    search_fields = ('full_name', 'user__email', 'user__phone')
    list_filter = ('age',)


class InstructorProfileAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'user', 'experience_years', 'specialization')
    search_fields = ('full_name', 'user__email', 'user__phone', 'specialization')
    list_filter = ('experience_years',)


admin.site.register(User, UserAdmin)
admin.site.register(StudentProfile, StudentProfileAdmin)
admin.site.register(InstructorProfile, InstructorProfileAdmin)
