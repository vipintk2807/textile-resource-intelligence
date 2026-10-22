"""Unit registry and conversions (calculations document, sections 5 and 15.1)."""

import random
from decimal import Decimal

import pytest

from textile_resource_intelligence.domain.errors import (
    IncompatibleUnitsError,
    QuantityError,
    UnknownUnitError,
)
from textile_resource_intelligence.domain.units import (
    are_compatible,
    convert_quantity,
    dimension_of,
    normalize_unit,
    to_canonical,
    unit_label,
    units_for,
)


@pytest.mark.parametrize("quantity,source,target,expected", [
    ("2.5", "MWh", "kWh", Decimal("2500")),
    ("1", "kWh", "MJ", Decimal("3.6")),
    ("2.5", "m3", "L", Decimal("2500")),
    ("1.5", "tonne", "kg", Decimal("1500")),
    ("2", "kg", "g", Decimal("2000")),
    ("500", "g", "kg", Decimal("0.5")),
    ("2500", "L", "m3", Decimal("2.5")),
])
def test_supported_conversions(quantity, source, target, expected):
    assert convert_quantity(quantity, source, target) == expected


@pytest.mark.parametrize("source,target", [
    ("kg", "L"), ("L", "kg"), ("L", "kWh"), ("kg", "kWh"), ("MJ", "kg"),
    ("kg", "m"), ("pcs", "kg"), ("m", "pcs"),
])
def test_incompatible_dimensions_are_rejected(source, target):
    with pytest.raises(IncompatibleUnitsError):
        convert_quantity(1, source, target)


def test_fuel_volume_to_energy_needs_a_fuel_specific_basis():
    with pytest.raises(IncompatibleUnitsError, match="fuel-specific"):
        convert_quantity(10, "L", "kWh")


def test_steam_mass_to_energy_needs_thermodynamic_information():
    with pytest.raises(IncompatibleUnitsError, match="thermodynamic"):
        convert_quantity(10, "kg", "MJ")


def test_mass_to_volume_needs_a_density_basis():
    with pytest.raises(IncompatibleUnitsError, match="density"):
        convert_quantity(10, "kg", "L")


@pytest.mark.parametrize("unit", ["bushel", "", None, "kwhh"])
def test_unknown_units_are_rejected_not_defaulted(unit):
    with pytest.raises(UnknownUnitError):
        convert_quantity(1, unit, "kWh")
    with pytest.raises(UnknownUnitError):
        normalize_unit(unit)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), "abc", None])
def test_invalid_quantities_are_not_converted(bad):
    with pytest.raises(QuantityError):
        convert_quantity(bad, "kg", "g")


def test_zero_stays_zero_and_same_unit_is_unchanged():
    assert convert_quantity(0, "MWh", "kWh") == 0
    assert convert_quantity("7.25", "kg", "kg") == Decimal("7.25")


def test_conversion_does_not_modify_inputs():
    original = Decimal("2.5")
    convert_quantity(original, "MWh", "kWh")
    assert original == Decimal("2.5")


def test_round_trip_recovers_the_original_value():
    rng = random.Random(1234)
    pairs = [("MWh", "kWh"), ("kWh", "MJ"), ("m3", "L"), ("tonne", "kg"), ("g", "kg"), ("tonne", "g")]
    for _ in range(200):
        value = Decimal(str(round(rng.uniform(0, 1e6), 4)))
        source, target = rng.choice(pairs)
        back = convert_quantity(convert_quantity(value, source, target), target, source)
        assert float(back) == pytest.approx(float(value), rel=1e-12)


def test_aliases_map_to_codes_and_case_is_ignored():
    assert normalize_unit("m³") == "m3"
    assert normalize_unit("KWH") == "kWh"
    assert normalize_unit("tonnes") == "tonne"
    assert normalize_unit("litres") == "L"


def test_dimensions_and_compatibility():
    assert dimension_of("MJ") == "energy"
    assert are_compatible("kg", "tonne")
    assert not are_compatible("kg", "L")
    assert not are_compatible("kg", "nonsense")


def test_canonical_conversion_reports_the_canonical_unit():
    assert to_canonical("2", "MWh") == (Decimal("2000"), "kWh")


def test_resource_and_production_unit_lists_are_distinct():
    assert "pcs" in units_for("production") and "pcs" not in units_for("resource")
    assert "kWh" in units_for("resource") and "kWh" not in units_for("production")


def test_unit_label_formats_compound_units():
    assert unit_label("m3/kg") == "m³/kg"
    assert unit_label(None) == ""
