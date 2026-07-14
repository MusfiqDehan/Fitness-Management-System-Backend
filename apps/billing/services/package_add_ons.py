"""Normalize priced package add-ons."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from rest_framework.exceptions import ValidationError


def normalize_package_add_ons(add_ons: list[Any] | None) -> list[dict]:
    """Accept legacy strings or {name, amount} objects; return object list."""
    if add_ons is None:
        return []
    if not isinstance(add_ons, list):
        raise ValidationError({"add_ons": "Must be a list."})

    normalized: list[dict] = []
    for idx, item in enumerate(add_ons):
        if isinstance(item, str):
            name = item.strip()
            if not name:
                continue
            normalized.append({"name": name, "amount": "0.00"})
            continue
        if not isinstance(item, dict):
            raise ValidationError({"add_ons": f"Add-on {idx} must be a string or object."})
        name = str(item.get("name") or "").strip()
        if not name:
            raise ValidationError({"add_ons": f"Add-on {idx} name is required."})
        try:
            amount = Decimal(str(item.get("amount", "0")))
        except (InvalidOperation, TypeError) as exc:
            raise ValidationError({"add_ons": f"Add-on {idx} amount is invalid."}) from exc
        if amount < 0:
            raise ValidationError({"add_ons": f"Add-on {idx} amount must be >= 0."})
        normalized.append({"name": name, "amount": f"{amount:.2f}"})
    return normalized
