"""Constants for the tenancy app — platform-level module keys.

Platform modules govern what platform employees (public-schema users)
can do in the superadmin dashboard. They are intentionally hard-coded
because adding a new platform module requires shipping new views.
"""

# Platform module keys — used by PlatformRolePermission.module_key
PLATFORM_MODULE_OVERVIEW = "platform.overview"
PLATFORM_MODULE_TENANTS = "platform.tenants"
PLATFORM_MODULE_TENANT_MANAGEMENT = "platform.tenant_management"
PLATFORM_MODULE_PACKAGES = "platform.packages"
PLATFORM_MODULE_ATTENDANCE = "platform.attendance"
PLATFORM_MODULE_FEATURES = "platform.features"
PLATFORM_MODULE_AUDIT_LOGS = "platform.audit_logs"
PLATFORM_MODULE_SUPPORT = "platform.support"
PLATFORM_MODULE_PLATFORM_USERS = "platform.platform_users"
PLATFORM_MODULE_BILLING = "platform.billing"
PLATFORM_MODULE_PAYMENTS = "platform.payments"
PLATFORM_MODULE_SETTINGS = "platform.settings"
PLATFORM_MODULE_EMAIL_SETTINGS = "platform.email_settings"
PLATFORM_MODULE_CMS_BLOGS = "platform.cms.blogs"
PLATFORM_MODULE_CMS_BANNERS = "platform.cms.banners"

PLATFORM_MODULES = {
    PLATFORM_MODULE_OVERVIEW: "Overview",
    PLATFORM_MODULE_TENANTS: "Tenants",
    PLATFORM_MODULE_TENANT_MANAGEMENT: "Tenant Management",
    PLATFORM_MODULE_PACKAGES: "Platform Packages",
    PLATFORM_MODULE_ATTENDANCE: "Platform Attendance",
    PLATFORM_MODULE_FEATURES: "Feature Registry",
    PLATFORM_MODULE_AUDIT_LOGS: "Audit Logs",
    PLATFORM_MODULE_SUPPORT: "Support Tickets",
    PLATFORM_MODULE_PLATFORM_USERS: "Platform Users",
    PLATFORM_MODULE_BILLING: "Platform Billing",
    PLATFORM_MODULE_PAYMENTS: "Platform Payments",
    PLATFORM_MODULE_SETTINGS: "Settings",
    PLATFORM_MODULE_EMAIL_SETTINGS: "Email Settings",
    PLATFORM_MODULE_CMS_BLOGS: "Blog Manager",
    PLATFORM_MODULE_CMS_BANNERS: "Banner Manager",
}

PLATFORM_MODULE_KEYS = list(PLATFORM_MODULES.keys())


# Predefined platform role slugs
PLATFORM_ROLE_SUPERADMIN = "superadmin"
PLATFORM_ROLE_PLATFORM_MANAGER = "platform_manager"
PLATFORM_ROLE_SUPPORT_AGENT = "support_agent"

# Default permission matrix for predefined platform roles
# (used by `seed_platform_roles` management command)
PREDEFINED_PLATFORM_ROLE_PERMISSIONS = {
    PLATFORM_ROLE_SUPERADMIN: {
        # Full access everywhere
        key: "full" for key in PLATFORM_MODULE_KEYS
    },
    PLATFORM_ROLE_PLATFORM_MANAGER: {
        PLATFORM_MODULE_OVERVIEW: "view",
        PLATFORM_MODULE_TENANTS: "full",
        PLATFORM_MODULE_TENANT_MANAGEMENT: "full",
        PLATFORM_MODULE_PACKAGES: "edit",
        PLATFORM_MODULE_ATTENDANCE: "view",
        PLATFORM_MODULE_FEATURES: "view",
        PLATFORM_MODULE_AUDIT_LOGS: "view",
        PLATFORM_MODULE_SUPPORT: "edit",
        PLATFORM_MODULE_PLATFORM_USERS: "view",
        PLATFORM_MODULE_BILLING: "view",
        PLATFORM_MODULE_PAYMENTS: "view",
        PLATFORM_MODULE_EMAIL_SETTINGS: "edit",
        PLATFORM_MODULE_CMS_BLOGS: "edit",
        PLATFORM_MODULE_CMS_BANNERS: "edit",
    },
    PLATFORM_ROLE_SUPPORT_AGENT: {
        PLATFORM_MODULE_OVERVIEW: "view",
        PLATFORM_MODULE_TENANTS: "view",
        PLATFORM_MODULE_TENANT_MANAGEMENT: "none",
        PLATFORM_MODULE_PACKAGES: "view",
        PLATFORM_MODULE_ATTENDANCE: "view",
        PLATFORM_MODULE_FEATURES: "none",
        PLATFORM_MODULE_AUDIT_LOGS: "view",
        PLATFORM_MODULE_SUPPORT: "edit",
        PLATFORM_MODULE_PLATFORM_USERS: "none",
        PLATFORM_MODULE_BILLING: "none",
        PLATFORM_MODULE_PAYMENTS: "none",
        PLATFORM_MODULE_EMAIL_SETTINGS: "none",
        PLATFORM_MODULE_CMS_BLOGS: "view",
        PLATFORM_MODULE_CMS_BANNERS: "view",
    },
}
