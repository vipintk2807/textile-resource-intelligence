"""Record and category validation (workflow section 6.6 and testing section 11)."""

from datetime import date
from decimal import Decimal

import pytest

from textile_resource_intelligence.domain.categories import validate_category_fields
from textile_resource_intelligence.domain.validation import (
    normalize_scope_key,
    parse_date,
    validate_record_fields,
)


def _resource(**overrides):
    base = dict(quantity="1200", unit="kWh", period_start="2025-01-01", period_end="2025-01-31")
    base.update(overrides)
    return validate_record_fields("resource", **base)


def _fields(issues):
    return {i.field for i in issues if i.is_error}


def test_valid_resource_record_passes_and_keeps_original_unit():
    fields, issues = _resource(unit="MWh", quantity="1.2")
    assert fields is not None and not issues
    assert fields.unit == "MWh" and fields.quantity == Decimal("1.2")


def test_single_date_record_has_equal_start_and_end():
    fields, _ = _resource(period_end=None)
    assert fields.period.is_single_date and fields.period.start == date(2025, 1, 1)


@pytest.mark.parametrize("override,field", [
    ({"quantity": ""}, "quantity"),
    ({"quantity": "abc"}, "quantity"),
    ({"quantity": "-5"}, "quantity"),
    ({"quantity": "nan"}, "quantity"),
    ({"unit": ""}, "unit"),
    ({"unit": "bushel"}, "unit"),
    ({"unit": "pcs"}, "unit"),
    ({"period_start": ""}, "period_start"),
    ({"period_start": "31/01/2025"}, "period_start"),
    ({"period_start": "2025-02-30"}, "period_start"),
    ({"period_end": "2024-12-31"}, "period_end"),
    ({"scope_key": "Dyeing Unit 1!"}, "scope_key"),
    ({"reference": "x" * 101}, "reference"),
    ({"record_type": "meter_reading"}, "record_type"),
    ({"record_type": "something"}, "record_type"),
])
def test_invalid_resource_input_is_reported_against_the_right_field(override, field):
    fields, issues = _resource(**override)
    assert fields is None
    assert field in _fields(issues)


def test_all_problems_are_reported_together():
    fields, issues = _resource(quantity="x", unit="bushel", period_start="nope")
    assert fields is None and _fields(issues) == {"quantity", "unit", "period_start"}


def test_zero_quantity_is_a_valid_recorded_value():
    fields, issues = _resource(quantity="0")
    assert fields is not None and fields.quantity == 0


def test_category_unit_restriction_is_enforced():
    fields, issues = _resource(unit="L", allowed_units=["kWh", "MWh"], category_name="Electricity")
    assert fields is None and "unit" in _fields(issues)
    assert any("Electricity" in i.message for i in issues)


def test_meter_reading_message_explains_the_limitation():
    _, issues = _resource(record_type="meter_reading")
    assert any("meter" in i.message.lower() for i in issues)


def test_production_allows_zero_but_rejects_negative_and_resource_only_units():
    fields, _ = validate_record_fields("production", quantity="0", unit="kg", period_start="2025-01-01")
    assert fields is not None
    fields, issues = validate_record_fields("production", quantity="-1", unit="kg", period_start="2025-01-01")
    assert fields is None and "quantity" in _fields(issues)
    fields, issues = validate_record_fields("production", quantity="1", unit="kWh", period_start="2025-01-01")
    assert fields is None and "unit" in _fields(issues)


def test_production_accepts_metres_and_pieces():
    for unit in ("m", "pcs", "tonne"):
        fields, _ = validate_record_fields("production", quantity="5", unit=unit, period_start="2025-01-01")
        assert fields is not None


def test_scope_key_normalisation():
    assert normalize_scope_key("  Dyeing-1 ") == "dyeing-1"
    assert normalize_scope_key("   ") is None
    assert normalize_scope_key(None) is None
    with pytest.raises(ValueError):
        normalize_scope_key("not valid")


@pytest.mark.parametrize("bad", ["", "2025/01/01", "2025-1-1", "1850-01-01", "2200-01-01", None, 5])
def test_parse_date_rejects_non_iso_or_out_of_range(bad):
    with pytest.raises(ValueError):
        parse_date(bad)


def test_category_validation_accepts_a_good_definition():
    fields, issues = validate_category_fields(" Reactive  dye ", "chemicals", "kg", ["kg", "g"])
    assert fields["name"] == "Reactive dye" and fields["allowed_units"] == ("kg", "g")


@pytest.mark.parametrize("args,field", [
    (("", "water", "L", ["L"]), "name"),
    (("123", "water", "L", ["L"]), "name"),
    (("Water", "plasma", "L", ["L"]), "resource_type"),
    (("Water", "water", "L", []), "allowed_units"),
    (("Water", "water", "kWh", ["L"]), "default_unit"),
    (("Water", "water", "L", ["pcs"]), "allowed_units"),
    (("Water", "water", "bushel", ["L"]), "default_unit"),
])
def test_invalid_category_definitions_are_rejected(args, field):
    fields, issues = validate_category_fields(*args)
    assert fields is None and field in _fields(issues)
