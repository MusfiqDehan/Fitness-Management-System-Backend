"""Shared normalisation for the tenant / platform brand colour fields.

Both ``GymProfile`` (tenant schema) and ``PlatformGymProfile`` (public schema)
expose ``primary_color`` / ``secondary_color``. Keeping the parsing in one place
means the two serializers cannot drift apart on what they accept.
"""

import re

HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-f]{3}|[0-9a-f]{6})$")

BRAND_COLOR_ERROR = "Enter a colour as a hex value, for example #ffc300."


def normalize_brand_color(value):
    """Return a canonical ``#rrggbb`` string, or ``""`` when unset.

    Accepts 3- or 6-digit hex, with or without the leading ``#``, in any case.
    An empty value is valid and means "fall back to the built-in palette".
    Raises ``ValueError`` for anything else so callers can turn it into their
    own validation error.
    """
    normalized = (value or "").strip().lower()
    if not normalized:
        return ""

    if not normalized.startswith("#"):
        normalized = f"#{normalized}"

    if not HEX_COLOR_RE.match(normalized):
        raise ValueError(BRAND_COLOR_ERROR)

    if len(normalized) == 4:
        # Expand the shorthand form: #abc -> #aabbcc
        normalized = "#" + "".join(char * 2 for char in normalized[1:])

    return normalized
