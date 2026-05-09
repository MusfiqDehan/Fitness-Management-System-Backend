from django.contrib import admin

from .models import Role, RolePermission, UserRole


class RolePermissionInline(admin.TabularInline):
    model = RolePermission
    extra = 0


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_system", "color", "created_at")
    list_filter = ("is_system",)
    search_fields = ("name", "slug")
    inlines = [RolePermissionInline]


@admin.register(UserRole)
class UserRoleAdmin(admin.ModelAdmin):
    list_display = ("user_email", "user_id", "role", "assigned_at")
    list_filter = ("role",)
    search_fields = ("user_email",)
