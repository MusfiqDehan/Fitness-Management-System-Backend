from django.contrib import admin
from .models import Member, MemberPackage, Attendance, Payment


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