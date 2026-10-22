"""Baseline comparison (calculations document section 9, testing section 10)."""

from datetime import date
from decimal import Decimal as D

import pytest

from textile_resource_intelligence.domain.calculations import (
    aggregate_production,
    aggregate_resources,
    compute_intensity,
)
from textile_resource_intelligence.domain.comparisons import compare_results, compare_values
from textile_resource_intelligence.domain.types import (
    CalcStatus,
    Category,
    Period,
    ProductionRecord,
    ResourceRecord,
)

JAN = Period(date(2025, 1, 1), date(2025, 1, 31))
FEB = Period(date(2025, 2, 1), date(2025, 2, 28))
CATS = {1: Category(1, "Electricity", "electricity", "kWh", ("kWh",)),
        2: Category(2, "Waste", "waste", "kg", ("kg",))}


@pytest.mark.parametrize("current,baseline,pct", [("1.8", "2.0", "-10"), ("2.0", "2.0", "0"), ("2.2", "2.0", "10")])
def test_percentage_change_cases(current, baseline, pct):
    result = compare_values(current, baseline, current_unit="kWh/kg", baseline_unit="kWh/kg")
    assert result.status is CalcStatus.VALID
    assert result.percent_change == D(pct)
    assert result.absolute_difference == D(current) - D(baseline)


def test_zero_baseline_keeps_difference_but_not_percentage():
    result = compare_values(1, 0)
    assert result.percent_change is None and result.absolute_difference == D(1)
    assert "zero" in result.percent_reason
    assert result.status is CalcStatus.VALID_WITH_WARNINGS


@pytest.mark.parametrize("current,baseline", [(1, None), (None, 2), ("x", 2), (1, "x"), (-1, 2), (1, -2),
                                              (float("nan"), 2), (1, float("inf"))])
def test_missing_or_invalid_values_make_the_comparison_unavailable(current, baseline):
    result = compare_values(current, baseline)
    assert result.status is CalcStatus.UNAVAILABLE and result.percent_change is None and result.reason


def test_incompatible_units_are_unavailable():
    result = compare_values(1, 2, current_unit="kWh/kg", baseline_unit="L/kg")
    assert result.status is CalcStatus.UNAVAILABLE and "incompatible" in result.reason


def _intensity(window, kwh, kg, scope=None, cat=1, unit="kWh"):
    res = [ResourceRecord(1, cat, D(kwh), unit, window, scope)]
    prod = [ProductionRecord(1, D(kg), "kg", window, scope)]
    r = aggregate_resources(res, window, CATS)[0]
    p = aggregate_production(prod, window)[0]
    return compute_intensity(r, p, window=window, production_dimension="mass")


def test_intensity_comparison_reports_traceable_references():
    baseline, current = _intensity(JAN, 1200, 600), _intensity(FEB, 900, 600)
    result = compare_results(current, baseline)
    assert result.status is CalcStatus.VALID
    assert result.baseline_value == D(2) and result.current_value == D("1.5")
    assert result.percent_change == D(-25) and result.absolute_difference == D("-0.5")
    assert "2025-01-01 to 2025-01-31" in result.baseline_reference
    assert "2025-02-01 to 2025-02-28" in result.current_reference


def test_missing_baseline_is_unavailable_with_reason():
    result = compare_results(_intensity(FEB, 900, 600), None)
    assert result.status is CalcStatus.UNAVAILABLE and "no baseline" in result.reason.lower()


def test_unavailable_baseline_result_propagates_reason():
    bad = _intensity(JAN, 1200, 0)
    result = compare_results(_intensity(FEB, 900, 600), bad)
    assert result.status is CalcStatus.UNAVAILABLE and "zero" in result.reason


def test_zero_baseline_intensity_gives_difference_without_percentage():
    result = compare_results(_intensity(FEB, 20, 600, cat=2, unit="kg"), _intensity(JAN, 0, 600, cat=2, unit="kg"))
    assert result.baseline_value == 0 and result.percent_change is None
    assert result.absolute_difference is not None and "zero" in result.percent_reason


def test_scope_and_category_mismatch_are_unavailable():
    a, b = _intensity(JAN, 1200, 600, scope="x"), _intensity(FEB, 900, 600)
    assert compare_results(b, a).status is CalcStatus.UNAVAILABLE
    assert "scope" in compare_results(b, a).reason
    c = _intensity(JAN, 20, 600, cat=2, unit="kg")
    assert "categories" in compare_results(b, c).reason


def test_identical_periods_are_flagged():
    a = _intensity(JAN, 1200, 600)
    result = compare_results(a, a)
    assert result.percent_change == 0 and any("identical" in w for w in result.warnings)


def test_partial_period_warning_is_carried_into_the_comparison():
    half = Period(date(2025, 1, 1), date(2025, 1, 15))
    partial = compute_intensity(
        aggregate_resources([ResourceRecord(1, 1, D(300), "kWh", half)], JAN, CATS)[0],
        aggregate_production([ProductionRecord(1, D(150), "kg", half)], JAN)[0],
        window=JAN, production_dimension="mass")
    assert partial.status is CalcStatus.VALID_WITH_WARNINGS
    result = compare_results(_intensity(FEB, 900, 600), partial)
    assert result.status is CalcStatus.VALID_WITH_WARNINGS
    assert any("Baseline period" in w for w in result.warnings)


def test_derived_values_with_many_decimals_are_comparable():
    result = compare_values(D(20) / D(600), D(1) / D(3))
    assert result.status is CalcStatus.VALID and result.percent_change is not None
