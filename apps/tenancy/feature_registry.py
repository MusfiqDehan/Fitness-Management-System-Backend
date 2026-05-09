"""Single source of truth for sidebar / RBAC features.

Two scopes (PLATFORM vs TENANT) plus a SHARED bucket (e.g. Settings) that is
visible to everyone authenticated, regardless of schema.

Anything that needs to render the sidebar, gate a route, or seed RolePermission
rows must derive from THIS file. Drift is detected by tests in
`apps.tenancy.test_feature_registry`.

Each leaf carries:
  - key:    the permission key (must match `apps.access.RolePermission.feature_key`
            for tenant features, or `PlatformRolePermission.module_key` for
            platform modules).
  - name:   human label shown in the sidebar.
  - route:  frontend path (None means "no sidebar link").
  - icon:   lucide-react icon NAME (a string). The frontend maps it to a
            component via a small dictionary.
  - badge:  optional pre-rendered badge text (e.g. "100").

Tenant features can be grouped via the `group` field on a top-level entry; the
`children` of that group share the same permission scope.
"""
from __future__ import annotations

from typing import TypedDict


class RegistryItem(TypedDict, total=False):
    key: str
    name: str
    route: str | None
    icon: str
    badge: str
    group: str
    children: list["RegistryItem"]


# ─── Platform scope (public-schema users) ─────────────────────────────────────
# Keys here MUST exist in `apps.tenancy.constants.PLATFORM_MODULES`.
PLATFORM_REGISTRY: list[RegistryItem] = [
    {
        "group": "Platform Admin",
        "children": [
            {
                "key": "platform.tenants",
                "name": "Tenants",
                "route": "/platform/tenants",
                "icon": "Building2",
            },
            {
                "key": "platform.platform_users",
                "name": "Platform Team",
                "route": "/platform/team",
                "icon": "UsersRound",
            },
            # The remaining platform modules below are gated and ready —
            # add their `route` once the corresponding pages ship.
            {
                "key": "platform.packages",
                "name": "Platform Packages",
                "route": "/platform/packages",
                "icon": "Boxes",
            },
            {
                "key": "platform.features",
                "name": "Feature Registry",
                "route": None,
                "icon": "ListChecks",
            },
            {
                "key": "platform.audit_logs",
                "name": "Audit Logs",
                "route": None,
                "icon": "FileSearch",
            },
            {
                "key": "platform.support",
                "name": "Support Tickets",
                "route": None,
                "icon": "LifeBuoy",
            },
            {
                "key": "platform.billing",
                "name": "Platform Billing",
                "route": None,
                "icon": "CreditCard",
            },
            {
                "key": "platform.tenant_management",
                "name": "Tenant Management",
                "route": None,
                "icon": "Settings2",
            },
        ],
    },
]


# ─── Tenant scope (subdomain users) ───────────────────────────────────────────
# Keys here MUST be present in `FULL_ACCESS_FEATURE_KEYS`
# (apps/access/management/commands/seed_tenant_roles.py).
TENANT_REGISTRY: list[RegistryItem] = [
    {
        "group": "Dashboard",
        "children": [
            {"key": "dashboard",          "name": "Overview",   "route": "/dashboard",  "icon": "LayoutGrid"},
            {"key": "members.attendance", "name": "Attendance", "route": "/attendance", "icon": "UserCheck"},
            {"key": "reports",            "name": "Reports",    "route": "/reports",    "icon": "BarChart3"},
        ],
    },
    {
        "group": "Members",
        "children": [
            {"key": "members", "name": "Members Overview", "route": "/members",     "icon": "PieChart"},
            {"key": "members", "name": "All Members",      "route": "/members/all", "icon": "Users", "badge": "100"},
        ],
    },
    {
        "group": "Finance",
        "children": [
            {"key": "payments",          "name": "Payments",  "route": "/payments",  "icon": "CreditCard"},
            {"key": "payments.invoices", "name": "Invoices",  "route": None,         "icon": "FileText"},
            {"key": "members.packages",  "name": "Packages",  "route": "/packages",  "icon": "Boxes"},
            {"key": "reminders",         "name": "Reminders", "route": "/reminders", "icon": "Bell"},
        ],
    },
    {
        "group": "Classes",
        "children": [
            {"key": "classes",     "name": "Schedule",    "route": "/schedule",    "icon": "CalendarDays"},
            {"key": "instructors", "name": "Instructors", "route": "/instructors", "icon": "UserCog"},
        ],
    },
    {
        "group": "Growth & Engagement",
        "children": [
            {"key": "crm.contacts",     "name": "Contact Manager",  "route": "/contacts",  "icon": "Phone"},
            {"key": "crm.inquiries",    "name": "Manage Inquiries", "route": "/inquiries", "icon": "FileText"},
            {"key": "classes",          "name": "Class Manager",    "route": "/classes",   "icon": "Server"},
            {"key": "classes.bookings", "name": "Booking Manager",  "route": "/bookings",  "icon": "CalendarRange"},
            {"key": "cms.blogs",        "name": "Blog Manager",     "route": "/blogs",     "icon": "CircleDashed"},
            {"key": "clubs",            "name": "Club Manager",     "route": "/clubs",     "icon": "Cloud"},
            {"key": "cms.banners",      "name": "Banner Manager",   "route": "/banners",   "icon": "MonitorPlay"},
        ],
    },
    {
        "group": "Access Control",
        "children": [
            {"key": "permissions",   "name": "Rules & Permission", "route": "/permissions", "icon": "ShieldCheck"},
        ],
    },
]


# ─── Shared (always shown to authenticated users) ────────────────────────────
SHARED_FEATURES: list[RegistryItem] = [
    {"key": "settings", "name": "Settings", "route": "/settings", "icon": "Settings"},
]


# ─── Helpers ──────────────────────────────────────────────────────────────────

def iter_tenant_leaf_keys() -> list[str]:
    """Flat de-duplicated list of every permission key referenced by the tenant
    registry. Used by the seed/sync command and by tests."""
    seen: list[str] = []
    for group in TENANT_REGISTRY:
        for item in group.get("children", []):
            key = item["key"]
            if key not in seen:
                seen.append(key)
    return seen


def iter_platform_leaf_keys() -> list[str]:
    seen: list[str] = []
    for group in PLATFORM_REGISTRY:
        for item in group.get("children", []):
            key = item["key"]
            if key not in seen:
                seen.append(key)
    return seen


def build_api_payload() -> dict:
    """The exact JSON the frontend consumes via /admin/feature-registry/."""
    def _strip(items: list[RegistryItem]) -> list[dict]:
        out: list[dict] = []
        for grp in items:
            out.append(
                {
                    "group": grp.get("group", ""),
                    "items": [
                        {
                            "key": it["key"],
                            "name": it["name"],
                            "route": it.get("route"),
                            "icon": it.get("icon"),
                            "badge": it.get("badge"),
                        }
                        for it in grp.get("children", [])
                        if it.get("route")  # only ship items that have a route
                    ],
                }
            )
        # Drop empty groups (all children had no route).
        return [g for g in out if g["items"]]

    return {
        "platform": _strip(PLATFORM_REGISTRY),
        "tenant": _strip(TENANT_REGISTRY),
        "shared": [
            {
                "key": it["key"],
                "name": it["name"],
                "route": it.get("route"),
                "icon": it.get("icon"),
            }
            for it in SHARED_FEATURES
        ],
    }
