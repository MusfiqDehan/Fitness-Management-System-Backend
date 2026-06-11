import decimal

from utils.cache_helpers import get_platform_settings_cached


def convert_currency(amount: decimal.Decimal, from_currency: str, to_currency: str) -> decimal.Decimal:
    """Dynamically converts direct amount from one currency to another using PlatformSettings.

    If conversion is disabled or exchange rates are unavailable, returned rate falls back gracefully.
    USD is treated as the base currency.
    """
    if not amount:
        return decimal.Decimal("0.00")

    from_currency = (from_currency or "USD").upper()
    to_currency = (to_currency or "USD").upper()

    if from_currency == to_currency:
        return amount

    settings = get_platform_settings_cached()

    # If conversion is disabled, skip translation
    if settings and not settings.get("enable_currency_conversion"):
        return amount

    usd_to_bdt_rate = decimal.Decimal("120.0000")
    rates = {}
    if settings:
        usd_to_bdt_rate = decimal.Decimal(str(settings.get("usd_to_bdt_rate", usd_to_bdt_rate)))
        rates = settings.get("exchange_rates") or {}

    # Synthesize standard matrix
    matrix = {
        "USD": decimal.Decimal("1.0000"),
        "BDT": usd_to_bdt_rate,
    }
    for k, v in rates.items():
        try:
            matrix[k.upper()] = decimal.Decimal(str(v))
        except (ValueError, TypeError, decimal.InvalidOperation):
            pass

    # Perform conversion with USD base
    # from_currency -> USD -> to_currency
    if from_currency not in matrix or to_currency not in matrix:
        # Fallback default: if BDT <-> USD not in rates but we have usd_to_bdt_rate
        if "BDT" not in matrix:
            matrix["BDT"] = usd_to_bdt_rate
        if from_currency not in matrix:
            # Can't translate, return original
            return amount
        if to_currency not in matrix:
            return amount

    amount_in_usd = amount / matrix[from_currency]
    converted_amount = amount_in_usd * matrix[to_currency]

    return converted_amount.quantize(decimal.Decimal(".01"), rounding=decimal.ROUND_HALF_UP)
