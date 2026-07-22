"""Normalize flexible payment line items."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from rest_framework.exceptions import ValidationError

ALLOWED_TYPES = frozenset({"package", "addon", "custom", "discount"})
CHARGE_TYPES = frozenset({"package", "addon", "custom"})


def normalize_line_items(items: list[Any] | None) -> list[dict]:
    if items is None:
        return []
    if not isinstance(items, list):
        raise ValidationError({"line_items": "Must be a list of objects."})

    normalized: list[dict] = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValidationError({"line_items": f"Item {idx} must be an object."})
        item_type = str(item.get("type") or "").strip().lower()
        name = str(item.get("name") or "").strip()
        if item_type not in ALLOWED_TYPES:
            raise ValidationError(
                {"line_items": f"Item {idx} type must be one of {sorted(ALLOWED_TYPES)}."}
            )
        if not name:
            raise ValidationError({"line_items": f"Item {idx} name is required."})
        try:
            amount = Decimal(str(item.get("amount", "0")))
        except (InvalidOperation, TypeError) as exc:
            raise ValidationError({"line_items": f"Item {idx} amount is invalid."}) from exc
        if amount < 0:
            raise ValidationError({"line_items": f"Item {idx} amount must be >= 0."})
        entry: dict[str, Any] = {
            "type": item_type,
            "name": name,
            "amount": f"{amount:.2f}",
        }
        ref = item.get("ref")
        if ref is not None and str(ref).strip():
            entry["ref"] = str(ref).strip()
        normalized.append(entry)
    return normalized


def total_from_line_items(items: list[dict] | None) -> Decimal:
    """Charges minus discount savings."""
    charges = Decimal("0.00")
    discounts = Decimal("0.00")
    for item in items or []:
        amount = Decimal(str(item.get("amount", "0")))
        if str(item.get("type") or "").lower() == "discount":
            discounts += amount
        else:
            charges += amount
    total = charges - discounts
    if total < 0:
        total = Decimal("0.00")
    return total.quantize(Decimal("0.01"))
