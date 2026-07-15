"""Reusable coupon-code normalization and format validation.

Rules (shared with the frontend):
- Letters (A–Z) and digits (0–9) only
- Stored / compared uppercase
- Max length 32
"""

from __future__ import annotations

import re

from django.core.exceptions import ValidationError

COUPON_CODE_MAX_LENGTH = 32
COUPON_CODE_PATTERN = re.compile(r"^[A-Z0-9]+$")

COUPON_CODE_FORMAT_MESSAGE = "Coupon code may only contain letters and numbers."
COUPON_CODE_LENGTH_MESSAGE = f"Coupon code must be at most {COUPON_CODE_MAX_LENGTH} characters."


def normalize_coupon_code(value: str | None) -> str | None:
    """Strip and uppercase; empty becomes None."""
    if value is None:
        return None
    code = str(value).strip().upper()
    return code or None


def validate_coupon_code_format(value: str | None) -> str | None:
    """Normalize and validate format. Returns normalized code or None if empty.

    Raises:
        ValidationError: when non-empty value fails alphanumeric / length rules.
    """
    code = normalize_coupon_code(value)
    if code is None:
        return None
    if len(code) > COUPON_CODE_MAX_LENGTH:
        raise ValidationError(COUPON_CODE_LENGTH_MESSAGE)
    if not COUPON_CODE_PATTERN.fullmatch(code):
        raise ValidationError(COUPON_CODE_FORMAT_MESSAGE)
    return code
