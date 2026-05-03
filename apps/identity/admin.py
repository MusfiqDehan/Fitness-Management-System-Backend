from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, StudentProfile, InstructorProfile

class UserAdmin(BaseUserAdmin):
    list_display = ('email', 'phone', 'role', 'is_staff', 'is_superuser', 'is_active', 'created_at')
    list_filter = ('role', 'is_staff', 'is_superuser', 'is_active')

    # Remove non-editable 'created_at' from fieldsets
    fieldsets = (
        (None, {'fields': ('email', 'phone', 'password')}),
        ('Permissions', {'fields': ('role', 'is_staff', 'is_superuser', 'is_active', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login',)}),  # Removed 'created_at'
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'phone', 'role', 'password1', 'password2', 'is_staff', 'is_superuser', 'is_active')}
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
