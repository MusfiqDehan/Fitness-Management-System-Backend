from django.contrib import admin
from django.utils.html import format_html
from .models import (
    Banner,
    GymClub,
    Facility,
    GymClass, 
    Category, 
    ClassSchedule,
    Blog,
    BlogCategory,
    Contact,
    FitHiveSupport,
    ClassBooking,
    Package, 
    PackageFeature, 
    PackageAddOn,
)


@admin.register(Banner)
class BannerAdmin(admin.ModelAdmin):
    list_display = (
        'fitness_name',
        'background_type',
        'preview',
        'is_active',
        'created_at',
    )

    list_filter = ('background_type', 'is_active')
    search_fields = ('fitness_name', 'title1', 'title2')

    readonly_fields = ('preview',)

    def preview(self, obj):
        if not obj.background_file:
            return "No file"

        if obj.background_type == 'image':
            return format_html(
                '<img src="{}" width="120" style="border-radius:8px;" />',
                obj.background_file.url
            )

        if obj.background_type == 'video':
            return format_html(
                '<video width="200" controls>'
                '<source src="{}" type="video/mp4">'
                'Your browser does not support the video tag.'
                '</video>',
                obj.background_file.url
            )

        return "Unsupported file"

    preview.short_description = "Preview"


@admin.register(Facility)
class FacilityAdmin(admin.ModelAdmin):
    list_display = ('id', 'name')
    search_fields = ('name',)


@admin.register(GymClub)
class GymClubAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'name',
        'image_preview',
        'phone_number',
        'email',
        'opening_time',
        'closing_time',
    )
    list_filter = ('opening_time', 'closing_time', 'facilities')
    search_fields = ('name', 'address', 'phone_number', 'email')
    filter_horizontal = ('facilities',)

    def image_preview(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" width="60" height="60" style="object-fit:cover;" />',
                obj.image.url
            )
        return "No Image"

    image_preview.short_description = "Image"

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "name")
    search_fields = ("name",)


@admin.register(ClassSchedule)
class ClassScheduleAdmin(admin.ModelAdmin):
    list_display = ("day", "time")
    list_filter = ("day",)


@admin.register(GymClass)
class GymClassAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "category",
        "level",
        "class_duration",
        "people",
    )
    list_filter = ("category", "level")
    filter_horizontal = ("class_schedule",)

@admin.register(ClassBooking)
class ClassBookingAdmin(admin.ModelAdmin):
    list_display = ('user', 'gym_class', 'status', 'phone', 'created_at')
    list_filter = ('status', 'gym_class')
    search_fields = ('user__username', 'user__email', 'gym_class__title', 'phone')
    readonly_fields = ('created_at',)


@admin.register(BlogCategory)
class BlogCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name',)
    ordering = ('name',)


@admin.register(Blog)
class BlogAdmin(admin.ModelAdmin):
    list_display = (
        'title',
        'category',
        'status',
        'author',
        'published_date',
        'created_at',
        'is_show_on_home_page',
    )
    list_filter = ('status', 'category', 'created_at')
    search_fields = ('title', 'description')
    prepopulated_fields = {'slug': ('title',)}
    readonly_fields = ('created_at',)
    autocomplete_fields = ('category', 'author')
    ordering = ('-created_at',)


# -----------------------------
# Contact Admin
# -----------------------------
@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "email",
        "phone",
        "preferred_club",
        "subject",
        "status",
        "created_at",
    )
    list_filter = ("status", "preferred_club", "created_at")
    search_fields = (
        "name",
        "email",
        "phone",
        "subject",
        "message",
    )
    list_editable = ("status",)
    ordering = ("-created_at",)
    readonly_fields = ("created_at",)

    fieldsets = (
        ("Contact Information", {
            "fields": ("name", "email", "phone", "preferred_club")
        }),
        ("Message Details", {
            "fields": ("subject", "message")
        }),
        ("Status", {
            "fields": ("status",)
        }),
        ("System Info", {
            "fields": ("created_at",)
        }),
    )


# -----------------------------
# FitHive Support Admin
# -----------------------------
@admin.register(FitHiveSupport)
class FitHiveSupportAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "email",
        "phone",
        "interested_in",
        "status",
        "created_at",
    )
    list_filter = ("status", "created_at")
    search_fields = (
        "name",
        "email",
        "phone",
        "interested_in",
    )
    list_editable = ("status",)
    ordering = ("-created_at",)
    readonly_fields = ("created_at",)

    fieldsets = (
        ("User Information", {
            "fields": ("name", "email", "phone")
        }),
        ("Interest Details", {
            "fields": ("interested_in",)
        }),
        ("Status", {
            "fields": ("status",)
        }),
        ("System Info", {
            "fields": ("created_at",)
        }),
    )


# package
# Inline for PackageFeature
class PackageFeatureInline(admin.TabularInline):
    model = PackageFeature
    extra = 1  # Number of empty forms to display
    min_num = 0
    verbose_name = "Feature"
    verbose_name_plural = "Features"

# Inline for PackageAddOn
class PackageAddOnInline(admin.TabularInline):
    model = PackageAddOn
    extra = 1
    min_num = 0
    verbose_name = "Add-On"
    verbose_name_plural = "Add-Ons"

# Main Package admin
@admin.register(Package)
class PackageAdmin(admin.ModelAdmin):
    list_display = ("name", "duration", "price", "is_popular", "is_active", "display_order")
    list_filter = ("is_popular", "is_active", "duration")
    search_fields = ("name", "description")
    ordering = ("display_order", "name")
    inlines = [PackageFeatureInline, PackageAddOnInline]