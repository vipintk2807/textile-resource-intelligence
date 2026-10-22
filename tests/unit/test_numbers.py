"""Strict numeric parsing: no silent coercion of invalid values."""

from decimal import Decimal

import pytest

from textile_resource_intelligence.domain.errors import QuantityError
from textile_resource_intelligence.domain.numbers import parse_decimal


@pytest.mark.parametrize("text,expected", [
    ("1200", Decimal("1200")),
    (" 1200.50 ", Decimal("1200.50")),
    ("0", Decimal("0")),
    ("-0", Decimal("0")),
    (".5", Decimal("0.5")),
    ("1e3", Decimal("1000")),
])
def test_valid_strings_are_parsed_exactly(text, expected):
    assert parse_decimal(text) == expected


def test_float_input_does_not_leak_binary_noise():
    assert parse_decimal(0.1) == Decimal("0.1")


def test_integer_and_decimal_inputs_are_accepted():
    assert parse_decimal(5) == Decimal(5)
    assert parse_decimal(Decimal("2.5")) == Decimal("2.5")


@pytest.mark.parametrize("bad", [
    None, "", "   ", "abc", "12abc", "1,200", "1_000", "NaN", "nan", "inf", "-Infinity",
    float("nan"), float("inf"), True, [1], "1e999", "0.0000000000001", "1e18",
])
def test_invalid_values_are_rejected(bad):
    with pytest.raises(QuantityError):
        parse_decimal(bad)


def test_missing_quantity_message_says_required():
    with pytest.raises(QuantityError, match="required"):
        parse_decimal("")


def test_thousands_separator_message_is_actionable():
    with pytest.raises(QuantityError, match="thousands"):
        parse_decimal("1,200")
