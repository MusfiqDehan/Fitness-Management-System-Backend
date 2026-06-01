from django.contrib import admin

from .models import Branch, BranchShiftRequest, Facility


@admin.register(Facility)
class FacilityAdmin(admin.ModelAdmin):
    list_display = ("id", "name")
    search_fields = ("name",)


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "city", "status", "manager", "is_active")
    list_filter = ("status", "is_active", "is_flagship", "show_on_homepage")
    search_fields = ("name", "city", "address", "email")
    filter_horizontal = ("facilities",)


@admin.register(BranchShiftRequest)
class BranchShiftRequestAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "member",
        "trainer",
        "from_branch",
        "to_branch",
        "status",
        "reviewed_by",
        "reviewed_at",
    )
    list_filter = ("status",)
    search_fields = ("reason", "decision_note")
