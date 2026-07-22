from django.contrib import admin
from .models import (
    Member,
    MemberPackage,
    Attendance,
    Payment,
    GymClass,
    GymSchedule,
    Discount,
    DiscountCondition,
    DiscountUsage,
)


class AttendanceInline(admin.TabularInline):
    model = Attendance
    extra = 0
    readonly_fields = ('check_in_time', 'check_out_time', 'entry_method')
    can_delete = False


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    readonly_fields = ('payment_type', 'amount', 'payment_date')
    can_delete = False


@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = (
        'full_name',
        'phone_number',
        'membership_type',
        'member_package',
        'start_date',
        'end_date',
        'remaining_days',
        'is_active',
        'is_expired'
    )

    list_filter = ('is_active', 'membership_type', 'member_package')
    search_fields = ('full_name', 'phone_number', 'card_id', 'fingerprint_id')
    readonly_fields = ('created_at', 'remaining_days', 'is_expired')

    inlines = [AttendanceInline, PaymentInline]

    def is_expired(self, obj):
        return obj.is_expired
    is_expired.boolean = True
    is_expired.short_description = 'Expired?'


@admin.register(MemberPackage)
class MemberPackageAdmin(admin.ModelAdmin):
    list_display = ('name', 'package_type', 'duration_in_days', 'price')
    list_filter = ('package_type',)
    search_fields = ('name',)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('member', 'payment_type', 'amount', 'payment_date')
    list_filter = ('payment_type', 'payment_date')
    search_fields = ('member__full_name', 'member__phone_number')


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ('member', 'check_in_time', 'check_out_time', 'entry_method')
    list_filter = ('entry_method',)
    search_fields = ('member__full_name', 'member__phone_number')


@admin.register(GymClass)
class GymClassAdmin(admin.ModelAdmin):
    list_display = ('name', 'class_type', 'level', 'instructor', 'duration_minutes', 'capacity')
    list_filter = ('class_type', 'level')
    search_fields = ('name', 'instructor')


@admin.register(GymSchedule)
class GymScheduleAdmin(admin.ModelAdmin):
    list_display = ('title', 'day_of_week', 'start_time', 'end_time', 'instructor', 'capacity')
    list_filter = ('day_of_week',)
    search_fields = ('title', 'instructor')

class DiscountConditionInline(admin.TabularInline):
    model = DiscountCondition
    extra = 0


@admin.register(Discount)
class DiscountAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'discount_type',
        'application_mode',
        'coupon_code',
        'priority',
        'show_list_price',
        'show_percent_badge',
        'is_active',
    )
    list_filter = (
        'discount_type',
        'application_mode',
        'show_list_price',
        'show_percent_badge',
        'is_active',
    )
    search_fields = ('name', 'coupon_code')
    inlines = [DiscountConditionInline]


@admin.register(DiscountUsage)
class DiscountUsageAdmin(admin.ModelAdmin):
    list_display = ('discount', 'member', 'payment', 'amount_saved', 'coupon_code_used', 'created_at')
    search_fields = ('coupon_code_used', 'discount__name')
