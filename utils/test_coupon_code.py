import pytest
from django.core.exceptions import ValidationError

from utils.coupon_code import (
    COUPON_CODE_MAX_LENGTH,
    normalize_coupon_code,
    validate_coupon_code_format,
)


def test_normalize_uppercases_and_strips():
    assert normalize_coupon_code("  summer10  ") == "SUMMER10"
    assert normalize_coupon_code("") is None
    assert normalize_coupon_code(None) is None


def test_validate_accepts_alphanumeric():
    assert validate_coupon_code_format("save20") == "SAVE20"
    assert validate_coupon_code_format("ABC123") == "ABC123"


def test_validate_rejects_symbols_and_spaces():
    with pytest.raises(ValidationError, match="letters and numbers"):
        validate_coupon_code_format("SAVE-20")
    with pytest.raises(ValidationError, match="letters and numbers"):
        validate_coupon_code_format("SAVE 20")


def test_validate_rejects_over_max_length():
    with pytest.raises(ValidationError, match="32"):
        validate_coupon_code_format("A" * (COUPON_CODE_MAX_LENGTH + 1))


def test_validate_allows_empty():
    assert validate_coupon_code_format("") is None
    assert validate_coupon_code_format(None) is None
