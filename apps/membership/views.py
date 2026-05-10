"""Legacy membership access views.

These are temporary compatibility shims that delegate to attendance-owned APIs.
"""

from apps.attendance.views import AccessCheckAPIView, MembersInsideAPIView

# Backward-compatible symbol names used by legacy membership URLs.
CheckAccessAPIView = AccessCheckAPIView