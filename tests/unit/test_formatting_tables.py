"""Display helpers and tables: rounding is display-only and unavailable is never zero."""

from datetime import date
from decimal import Decimal as D

from textile_resource_intelligence.domain.calculations import (
    aggregate_production,
    aggregate_resources,
    compute_intensity,
)
from textile_resource_intelligence.domain.types import (
    CalcStatus,
    Category,
    Period,
    ProductionRecord,
    ResourceRecord,
)
from textile_resource_intelligence.ui.formatting import (
    comparison_direction,
    format_decimal,
    format_percent,
    format_quantity,
    format_raw_quantity,
    format_signed,
    quality_text,
    status_text,
)
from textile_resource_intelligence.ui.tables import intensities_frame, resource_records_frame, totals_frame

JAN = Period(date(2025, 1, 1), date(2025, 1, 31))
CATS = {1: Category(1, "Electricity", "electricity", "kWh", ("kWh",))}


def test_numbers_get_thousands_separators_and_units():
    assert format_quantity(D(1200), "kWh", 0) == "1,200 kWh"
    assert format_quantity(D("2"), "kWh/kg", 2) == "2.00 kWh/kg"
    assert format_quantity(D("2.5"), "m3", 1) == "2.5 m³"


def test_missing_values_are_unavailable_never_zero():
    assert format_decimal(None) == "Unavailable" and format_quantity(None, "kWh") == "Unavailable"
    assert format_percent(None) == "Unavailable" and format_signed(None, "kWh") == "Unavailable"
    assert format_decimal(D(0)) == "0.00"


def test_rounding_is_half_up_for_display_only():
    value = D("1.005")
    assert format_decimal(value, 2) == "1.01" and value == D("1.005")


def test_percent_format_states_the_baseline():
    assert format_percent(D("-10")) == "-10.0% versus baseline"
    assert format_percent(D("12.34")) == "+12.3% versus baseline"
    assert format_percent(D("0")) == "0.0% versus baseline"


def test_raw_quantity_keeps_precision_without_padding():
    assert format_raw_quantity(D("1200.500")) == "1,200.5"
    assert format_raw_quantity(D("0.000125")) == "0.000125"
    assert format_raw_quantity(D("3")) == "3"


def test_status_text_never_relies_on_colour_alone():
    assert "Unavailable" in status_text(CalcStatus.UNAVAILABLE)
    assert "warnings" in status_text(CalcStatus.VALID_WITH_WARNINGS)
    assert "review" in quality_text("review").lower()


def test_direction_wording_is_neutral():
    assert comparison_direction(D(-5)) == "lower" and comparison_direction(D(5)) == "higher"
    assert comparison_direction(D(0)) == "unchanged" and comparison_direction(None) == "not available"


def test_tables_show_units_and_unavailable_text():
    res = [ResourceRecord(1, 1, D(1200), "kWh", JAN)]
    totals = aggregate_resources(res, JAN, CATS)
    frame = totals_frame(totals)
    assert frame.loc[0, "Total consumption"] == "1,200.00" and frame.loc[0, "Unit"] == "kWh"
    assert frame.loc[0, "Coverage"] == "31 of 31 days"
    intensity = compute_intensity(totals[0], None, window=JAN, production_dimension="mass")
    row = intensities_frame([intensity]).iloc[0]
    assert row["Intensity"] == "Unavailable" and row["Production"] == "Unavailable"
    ok = compute_intensity(totals[0], aggregate_production([ProductionRecord(1, D(600), "kg", JAN)], JAN)[0],
                           window=JAN, production_dimension="mass")
    assert intensities_frame([ok]).iloc[0]["Intensity"] == "2.00 kWh/kg"


def test_record_table_keeps_the_original_unit():
    frame = resource_records_frame([ResourceRecord(5, 1, D("1.2"), "MWh", JAN)], CATS, {})
    assert frame.loc[0, "Unit"] == "MWh" and frame.loc[0, "Quantity (as recorded)"] == "1.2"
    assert frame.loc[0, "Resource category"] == "Electricity" and frame.loc[0, "Scope"] == "Overall (no scope)"
