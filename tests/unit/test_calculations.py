"""Aggregation and intensity (calculations document, sections 6-8, 11, 15).

All numbers are synthetic test values, not measurements or benchmarks.
"""

import random
from datetime import date
from decimal import Decimal as D

import pytest

from textile_resource_intelligence.domain.calculations import (
    aggregate_production,
    aggregate_resources,
    calculate_intensity,
    calculate_percentage_change,
    compute_intensities,
    compute_intensity,
    make_buckets,
    merge_periods,
    overall_intensity,
)
from textile_resource_intelligence.domain.errors import CalculationUnavailableError
from textile_resource_intelligence.domain.types import (
    CalcStatus,
    Category,
    Period,
    ProductionRecord,
    ResourceRecord,
)

JAN = Period(date(2025, 1, 1), date(2025, 1, 31))
FEB = Period(date(2025, 2, 1), date(2025, 2, 28))
JAN_FEB = Period(date(2025, 1, 1), date(2025, 2, 28))

CATS = {
    1: Category(1, "Electricity", "electricity", "kWh", ("kWh", "MWh")),
    2: Category(2, "Water", "water", "L", ("L", "m3")),
    3: Category(3, "Chemicals", "chemicals", "kg", ("kg", "g", "L", "m3")),
    4: Category(4, "Dye A", "chemicals", "kg", ("kg", "g", "L", "m3")),
}


def res(i, cat, qty, unit, period, scope=None, source="manual", ref=None):
    return ResourceRecord(i, cat, D(str(qty)), unit, period, scope, ref, None, source)


def prod(i, qty, unit, period, scope=None, source="manual"):
    return ProductionRecord(i, D(str(qty)), unit, period, scope, None, None, source)


def _intensity(resources, productions, window, basis="mass", cat=1, scope=None):
    r = [x for x in aggregate_resources(resources, window, CATS) if x.category_id == cat and x.scope_key == scope]
    p = [x for x in aggregate_production(productions, window) if x.dimension == basis and x.scope_key == scope]
    return compute_intensity(r[0] if r else None, p[0] if p else None, window=window, production_dimension=basis,
                             category_id=cat, scope_key=scope)


# ---------------------------------------------------------------- scalar functions
@pytest.mark.parametrize("c,p,expected", [(1200, 600, "2"), (400, 200, "2"), (3000, 600, "5"), (0, 600, "0")])
def test_intensity_scalar_examples(c, p, expected):
    assert calculate_intensity(c, p) == D(expected)


@pytest.mark.parametrize("c,p", [(100, 0), (100, None), (None, 100), (float("nan"), 5), (5, float("inf")),
                                 (-1, 5), (5, -1), ("abc", 5)])
def test_intensity_rejects_invalid_or_missing_inputs(c, p):
    with pytest.raises(CalculationUnavailableError):
        calculate_intensity(c, p)


def test_zero_production_message_names_the_cause():
    with pytest.raises(CalculationUnavailableError, match="production quantity is zero"):
        calculate_intensity(10, 0)


def test_percentage_change_examples():
    assert calculate_percentage_change("1.8", "2.0") == D("-10")
    assert calculate_percentage_change("2.0", "2.0") == D("0")
    assert calculate_percentage_change("2.2", "2.0") == D("10")


@pytest.mark.parametrize("current,baseline", [(1, 0), (1, None), (None, 1), (1, "x"), (-1, 2)])
def test_percentage_change_unavailable_cases(current, baseline):
    with pytest.raises(CalculationUnavailableError):
        calculate_percentage_change(current, baseline)


# ---------------------------------------------------------- resource aggregation
def test_compatible_records_are_summed_after_unit_conversion():
    recs = [res(1, 1, 1, "MWh", JAN), res(2, 1, 200, "kWh", JAN)]
    (total,) = aggregate_resources(recs, JAN, CATS)
    assert total.value == D(1200) and total.unit == "kWh" and total.record_ids == (1, 2)
    assert total.status is CalcStatus.VALID and total.coverage_complete


def test_original_records_are_not_modified_by_aggregation():
    rec = res(1, 1, 1, "MWh", JAN)
    aggregate_resources([rec], JAN, CATS)
    assert rec.quantity == D(1) and rec.unit == "MWh"


def test_categories_are_never_combined_even_with_the_same_unit():
    recs = [res(1, 3, 10, "kg", JAN), res(2, 4, 20, "kg", JAN)]
    totals = aggregate_resources(recs, JAN, CATS)
    assert sorted((t.category_name, t.value) for t in totals) == [("Chemicals", D(10)), ("Dye A", D(20))]


def test_incompatible_dimensions_stay_separate_groups():
    recs = [res(1, 3, 10, "kg", JAN), res(2, 3, 5, "L", JAN)]
    totals = aggregate_resources(recs, JAN, CATS)
    assert {(t.dimension, t.value) for t in totals} == {("mass", D(10)), ("volume", D(5))}


def test_scopes_are_not_aggregated_together():
    recs = [res(1, 1, 10, "kWh", JAN, scope="a"), res(2, 1, 20, "kWh", JAN, scope=None)]
    totals = aggregate_resources(recs, JAN, CATS)
    assert {(t.scope_key, t.value) for t in totals} == {("a", D(10)), (None, D(20))}


def test_periods_are_separated_by_the_requested_window():
    recs = [res(1, 1, 1200, "kWh", JAN), res(2, 1, 900, "kWh", FEB)]
    assert aggregate_resources(recs, JAN, CATS)[0].value == D(1200)
    assert aggregate_resources(recs, FEB, CATS)[0].value == D(900)
    assert aggregate_resources(recs, Period(date(2025, 3, 1), date(2025, 3, 31)), CATS) == []


def test_identical_quantities_are_not_deduplicated():
    recs = [res(1, 1, 100, "kWh", JAN), res(2, 1, 100, "kWh", JAN)]
    assert aggregate_resources(recs, JAN, CATS)[0].value == D(200)


def test_recorded_zero_is_a_valid_total_not_unavailable():
    (total,) = aggregate_resources([res(1, 1, 0, "kWh", JAN)], JAN, CATS)
    assert total.value == D(0) and total.is_available


def test_partial_coverage_is_flagged_not_called_complete():
    half = Period(date(2025, 1, 1), date(2025, 1, 15))
    (total,) = aggregate_resources([res(1, 1, 500, "kWh", half)], JAN, CATS)
    assert total.status is CalcStatus.VALID_WITH_WARNINGS
    assert not total.coverage_complete and total.coverage_days == 15
    assert any("15 of 31" in w for w in total.warnings)


def test_daily_records_covering_the_month_count_as_full_coverage():
    days = [res(i, 1, 10, "kWh", Period(date(2025, 2, i), date(2025, 2, i))) for i in range(1, 29)]
    (total,) = aggregate_resources(days, FEB, CATS)
    assert total.value == D(280) and total.coverage_complete and total.status is CalcStatus.VALID


def test_record_straddling_the_window_is_never_prorated():
    long = Period(date(2025, 1, 15), date(2025, 2, 14))
    (total,) = aggregate_resources([res(1, 1, 300, "kWh", long)], JAN, CATS)
    assert total.status is CalcStatus.UNAVAILABLE and total.value is None
    assert "boundary" in total.reason


def test_straddling_record_is_excluded_with_a_warning_when_others_fit():
    long = Period(date(2025, 1, 15), date(2025, 2, 14))
    recs = [res(1, 1, 300, "kWh", long), res(2, 1, 100, "kWh", JAN)]
    (total,) = aggregate_resources(recs, JAN, CATS)
    assert total.value == D(100) and total.status is CalcStatus.VALID_WITH_WARNINGS


def test_overlapping_but_different_intervals_make_the_total_unavailable():
    week = Period(date(2025, 1, 1), date(2025, 1, 7))
    recs = [res(1, 1, 100, "kWh", JAN), res(2, 1, 20, "kWh", week)]
    (total,) = aggregate_resources(recs, JAN, CATS)
    assert total.status is CalcStatus.UNAVAILABLE and "overlapping" in total.reason


def test_unknown_unit_makes_the_group_unavailable_instead_of_being_dropped():
    recs = [res(1, 1, 100, "kWh", JAN), res(2, 1, 5, "bushel", JAN)]
    totals = aggregate_resources(recs, JAN, CATS)
    bad = [t for t in totals if t.status is CalcStatus.UNAVAILABLE]
    assert bad and "unknown unit" in bad[0].reason


def test_empty_selection_returns_no_results():
    assert aggregate_resources([], JAN, CATS) == []
    assert aggregate_production([], JAN) == []


def test_order_of_records_does_not_change_the_total():
    rng = random.Random(7)
    base = [res(i, 1, rng.randint(1, 1000), "kWh", JAN) for i in range(1, 30)]
    shuffled = base[:]
    rng.shuffle(shuffled)
    assert aggregate_resources(base, JAN, CATS)[0].value == aggregate_resources(shuffled, JAN, CATS)[0].value


# ----------------------------------------------------------- production aggregation
def test_compatible_production_is_summed_in_canonical_units():
    (total,) = aggregate_production([prod(1, 1, "tonne", JAN), prod(2, 500, "kg", JAN)], JAN)
    assert total.value == D(1500) and total.unit == "kg"


def test_kilograms_and_metres_are_never_added():
    totals = aggregate_production([prod(1, 600, "kg", JAN), prod(2, 3000, "m", JAN)], JAN)
    assert {(t.dimension, t.value) for t in totals} == {("mass", D(600)), ("length", D(3000))}


def test_production_scopes_are_kept_apart():
    totals = aggregate_production([prod(1, 600, "kg", JAN, "a"), prod(2, 400, "kg", JAN)], JAN)
    assert {(t.scope_key, t.value) for t in totals} == {("a", D(600)), (None, D(400))}


def test_zero_production_is_kept_as_a_valid_total():
    (total,) = aggregate_production([prod(1, 0, "kg", JAN)], JAN)
    assert total.value == 0 and total.is_available


# ------------------------------------------------------------------------ intensity
def test_synthetic_example_1200_kwh_over_600_kg_is_2_kwh_per_kg():
    result = _intensity([res(1, 1, 1200, "kWh", JAN)], [prod(1, 600, "kg", JAN)], JAN)
    assert result.value == D(2) and result.unit == "kWh/kg" and result.status is CalcStatus.VALID
    assert result.record_ids == (1,) and result.production_record_ids == (1,)
    assert result.numerator.value == D(1200) and result.denominator.value == D(600)


def test_water_example_is_5_l_per_kg():
    result = _intensity([res(1, 2, 3000, "L", JAN)], [prod(1, 600, "kg", JAN)], JAN, cat=2)
    assert result.value == D(5) and result.unit == "L/kg"


def test_unit_conversion_happens_before_division():
    result = _intensity([res(1, 1, "1.2", "MWh", JAN)], [prod(1, "0.6", "tonne", JAN)], JAN)
    assert result.value == D(2) and result.unit == "kWh/kg"


def test_missing_production_is_unavailable_not_zero():
    result = _intensity([res(1, 1, 1200, "kWh", JAN)], [], JAN)
    assert result.status is CalcStatus.UNAVAILABLE and result.value is None
    assert "no mass-based production" in result.reason


def test_zero_production_is_unavailable():
    result = _intensity([res(1, 1, 1200, "kWh", JAN)], [prod(1, 0, "kg", JAN)], JAN)
    assert result.status is CalcStatus.UNAVAILABLE and "zero" in result.reason


def test_missing_resource_is_unavailable():
    result = _intensity([], [prod(1, 600, "kg", JAN)], JAN)
    assert result.status is CalcStatus.UNAVAILABLE


def test_incompatible_scope_is_not_used_as_denominator():
    result = _intensity([res(1, 1, 1200, "kWh", JAN, scope="a")], [prod(1, 600, "kg", JAN, scope=None)],
                        JAN, scope="a")
    assert result.status is CalcStatus.UNAVAILABLE


def test_different_production_basis_is_not_substituted():
    result = _intensity([res(1, 1, 1200, "kWh", JAN)], [prod(1, 3000, "m", JAN)], JAN, basis="mass")
    assert result.status is CalcStatus.UNAVAILABLE
    metres = _intensity([res(1, 1, 1200, "kWh", JAN)], [prod(1, 3000, "m", JAN)], JAN, basis="length")
    assert metres.value == D("0.4") and metres.unit == "kWh/m"


def test_misaligned_coverage_makes_intensity_unavailable():
    half = Period(date(2025, 1, 1), date(2025, 1, 15))
    result = _intensity([res(1, 1, 500, "kWh", half)], [prod(1, 600, "kg", JAN)], JAN)
    assert result.status is CalcStatus.UNAVAILABLE and "differ" in result.reason


def test_identical_partial_coverage_is_calculated_with_a_warning():
    half = Period(date(2025, 1, 1), date(2025, 1, 15))
    result = _intensity([res(1, 1, 300, "kWh", half)], [prod(1, 150, "kg", half)], JAN)
    assert result.value == D(2) and result.status is CalcStatus.VALID_WITH_WARNINGS


def test_resource_total_unavailable_propagates_reason():
    week = Period(date(2025, 1, 1), date(2025, 1, 7))
    recs = [res(1, 1, 100, "kWh", JAN), res(2, 1, 20, "kWh", week)]
    result = _intensity(recs, [prod(1, 600, "kg", JAN)], JAN)
    assert result.status is CalcStatus.UNAVAILABLE and "overlapping" in result.reason


def test_compute_intensities_pairs_each_resource_with_its_scope():
    recs = [res(1, 1, 1200, "kWh", JAN), res(2, 1, 500, "kWh", JAN, scope="a")]
    prods = [prod(1, 600, "kg", JAN), prod(2, 400, "kg", JAN, scope="a")]
    results = compute_intensities(aggregate_resources(recs, JAN, CATS), aggregate_production(prods, JAN),
                                  window=JAN, production_dimension="mass")
    assert {(r.scope_key, r.value) for r in results} == {(None, D(2)), ("a", D("1.25"))}


# --------------------------------------------------------- multi-period aggregation
def test_overall_intensity_uses_summed_quantities_not_a_mean():
    recs = [res(1, 1, 1200, "kWh", JAN), res(2, 1, 900, "kWh", FEB)]
    prods = [prod(1, 600, "kg", JAN), prod(2, 600, "kg", FEB)]
    periods = [_intensity(recs, prods, w) for w in (JAN, FEB)]
    assert [p.value for p in periods] == [D(2), D("1.5")]
    overall = overall_intensity(periods, window=JAN_FEB)
    assert overall.value == D("1.75") and overall.unit == "kWh/kg"


def test_overall_water_example_is_4_5_l_per_kg():
    recs = [res(1, 2, 3000, "L", JAN), res(2, 2, 2400, "L", FEB)]
    prods = [prod(1, 600, "kg", JAN), prod(2, 600, "kg", FEB)]
    periods = [_intensity(recs, prods, w, cat=2) for w in (JAN, FEB)]
    assert overall_intensity(periods, window=JAN_FEB).value == D("4.5")


def test_overall_differs_from_unweighted_mean_when_production_differs():
    recs = [res(1, 1, 100, "kWh", JAN), res(2, 1, 300, "kWh", FEB)]
    prods = [prod(1, 100, "kg", JAN), prod(2, 900, "kg", FEB)]
    periods = [_intensity(recs, prods, w) for w in (JAN, FEB)]
    mean = sum(p.value for p in periods) / 2  # (1 + 0.3333) / 2
    overall = overall_intensity(periods, window=JAN_FEB).value
    assert overall == D("0.4") and float(overall) != pytest.approx(float(mean))


def test_overall_equals_direct_ratio_over_the_whole_window():
    recs = [res(1, 1, 1200, "kWh", JAN), res(2, 1, 900, "kWh", FEB)]
    prods = [prod(1, 600, "kg", JAN), prod(2, 600, "kg", FEB)]
    direct = _intensity(recs, prods, JAN_FEB)
    assert direct.value == D("1.75")


def test_overall_skips_invalid_periods_and_says_so():
    recs = [res(1, 1, 1200, "kWh", JAN), res(2, 1, 900, "kWh", FEB)]
    prods = [prod(1, 600, "kg", JAN)]
    periods = [_intensity(recs, prods, w) for w in (JAN, FEB)]
    overall = overall_intensity(periods, window=JAN_FEB)
    assert overall.value == D(2) and overall.status is CalcStatus.VALID_WITH_WARNINGS
    assert any("1 of 2" in w for w in overall.warnings)


def test_overall_is_unavailable_when_no_period_is_valid():
    periods = [_intensity([res(1, 1, 1, "kWh", JAN)], [], JAN)]
    assert overall_intensity(periods, window=JAN).status is CalcStatus.UNAVAILABLE


def test_intensity_invariants_hold_for_random_valid_inputs():
    rng = random.Random(99)
    for _ in range(200):
        c = D(rng.randint(1, 10_000))
        p = D(rng.randint(1, 10_000))
        base = calculate_intensity(c, p)
        assert calculate_intensity(c + rng.randint(0, 50), p) >= base
        assert calculate_intensity(c, p + rng.randint(0, 50)) <= base
        assert calculate_intensity(c, p) * p == pytest.approx(float(c))


# ----------------------------------------------------------------- periods / buckets
def test_merge_periods_joins_overlapping_and_adjacent_days():
    a = Period(date(2025, 1, 1), date(2025, 1, 10))
    b = Period(date(2025, 1, 11), date(2025, 1, 20))
    c = Period(date(2025, 1, 25), date(2025, 1, 31))
    assert merge_periods([c, b, a]) == (Period(date(2025, 1, 1), date(2025, 1, 20)), c)


def test_month_buckets_are_clipped_to_the_window():
    window = Period(date(2025, 1, 15), date(2025, 3, 10))
    buckets = make_buckets(window, "month")
    assert buckets[0] == Period(date(2025, 1, 15), date(2025, 1, 31))
    assert buckets[1] == Period(date(2025, 2, 1), date(2025, 2, 28))
    assert buckets[-1] == Period(date(2025, 3, 1), date(2025, 3, 10))


def test_december_rolls_into_the_next_year():
    buckets = make_buckets(Period(date(2025, 12, 1), date(2026, 1, 31)), "month")
    assert [b.start for b in buckets] == [date(2025, 12, 1), date(2026, 1, 1)]


def test_too_many_daily_buckets_are_refused():
    with pytest.raises(ValueError):
        make_buckets(Period(date(2024, 1, 1), date(2025, 12, 31)), "day")
