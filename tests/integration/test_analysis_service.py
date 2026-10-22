"""Analysis workflows (workflow section 17 scenarios) using the synthetic demo dataset."""

from datetime import date
from decimal import Decimal as D

from textile_resource_intelligence.domain.types import CalcStatus, Period
from textile_resource_intelligence.schemas import ProductionRecordInput, ResourceRecordInput

JAN = Period(date(2025, 1, 1), date(2025, 1, 31))
FEB = Period(date(2025, 2, 1), date(2025, 2, 28))
MAR = Period(date(2025, 3, 1), date(2025, 3, 31))
APR = Period(date(2025, 4, 1), date(2025, 4, 30))
MAY = Period(date(2025, 5, 1), date(2025, 5, 31))
JUN = Period(date(2025, 6, 1), date(2025, 6, 30))
JAN_FEB = Period(date(2025, 1, 1), date(2025, 2, 28))


def _find(items, name, scope=None):
    return [i for i in items if i.category_name == name and i.scope_key == scope]


def test_empty_database_gives_an_empty_overview(services):
    overview = services.analysis.overview(JAN)
    assert not overview.has_any_data and overview.resource_totals == () and overview.intensities == ()


def test_scenario_c_electricity_intensity_is_2_kwh_per_kg(services):
    services.demo.load()
    (item,) = _find(services.analysis.overview(JAN).intensities, "Electricity")
    assert item.value == D(2) and item.unit == "kWh/kg"
    assert item.numerator.value == D(1200) and item.denominator.value == D(600)
    assert "demo" in item.source_types


def test_water_and_february_values(services):
    services.demo.load()
    jan = services.analysis.overview(JAN)
    feb = services.analysis.overview(FEB)
    assert _find(jan.intensities, "Water")[0].value == D(5)
    assert _find(feb.intensities, "Electricity")[0].value == D("1.5")
    assert _find(feb.intensities, "Water")[0].value == D(4)


def test_overall_two_month_window_matches_the_specification(services):
    services.demo.load()
    overview = services.analysis.overview(JAN_FEB)
    assert _find(overview.intensities, "Electricity")[0].value == D("1.75")
    assert _find(overview.intensities, "Water")[0].value == D("4.5")


def test_scenario_d_missing_denominator_keeps_the_total(services):
    services.demo.load()
    overview = services.analysis.overview(MAR)
    (total,) = _find(overview.resource_totals, "Electricity")
    assert total.value == D(1000)
    intensities = overview.intensities
    assert not intensities or all(i.status is CalcStatus.UNAVAILABLE for i in intensities)


def test_zero_production_makes_the_intensity_unavailable(services):
    services.demo.load()
    (item,) = _find(services.analysis.overview(APR).intensities, "Electricity")
    assert item.status is CalcStatus.UNAVAILABLE and "zero" in item.reason and item.value is None


def test_partial_resource_coverage_is_not_divided_by_full_month_production(services):
    services.demo.load()
    overview = services.analysis.overview(MAY)
    (item,) = _find(overview.intensities, "Electricity")
    assert item.status is CalcStatus.UNAVAILABLE
    assert any("incomplete" in w.message for w in overview.warnings)


def test_mwh_is_converted_before_the_division(services):
    services.demo.load()
    (item,) = _find(services.analysis.overview(JUN).intensities, "Electricity")
    assert item.value == D(2) and item.numerator.value == D(1100)


def test_chemicals_in_mass_and_volume_stay_separate(services):
    services.demo.load()
    totals = _find(services.analysis.overview(JAN).resource_totals, "Chemicals")
    assert {(t.dimension, t.value) for t in totals} == {("mass", D(50)), ("volume", D(20))}


def test_scopes_have_separate_results(services):
    services.demo.load()
    overview = services.analysis.overview(JAN)
    scoped = _find(overview.intensities, "Electricity", "demo-dyeing")[0]
    assert scoped.value == D("1.25")


def test_possible_duplicates_and_missing_production_surface_as_warnings(services):
    services.demo.load()
    kinds = {w.kind for w in services.analysis.overview(JAN).warnings}
    assert "possible_duplicates" in kinds
    assert "missing_production" in {w.kind for w in services.analysis.overview(MAR).warnings}


def test_production_basis_can_be_switched_but_never_mixed(services):
    services.demo.load()
    overview = services.analysis.overview(FEB, "length")
    assert overview.production_dimension == "length"
    (item,) = _find(overview.intensities, "Electricity")
    assert item.value == D("0.3") and item.unit == "kWh/m"
    mass = services.analysis.overview(FEB, "mass")
    assert _find(mass.intensities, "Electricity")[0].value == D("1.5")


def test_scenario_e_baseline_comparison(services):
    services.demo.load()
    cid = services.category_id("Electricity")
    view = services.analysis.compare(cid, None, FEB, JAN, resource_dimension="energy", production_dimension="mass")
    cmp = view.intensity_comparison
    assert cmp.baseline_value == D(2) and cmp.current_value == D("1.5")
    assert cmp.percent_change == D(-25) and cmp.absolute_difference == D("-0.5")
    assert view.total_comparison.percent_change == D(-25)  # 900 vs 1200 kWh
    assert view.production_comparison.percent_change == D(0)
    assert "2025-01-01" in cmp.baseline_reference


def test_scenario_f_zero_baseline(services):
    services.demo.load()
    cid = services.category_id("Waste")
    view = services.analysis.compare(cid, None, FEB, JAN, resource_dimension="mass", production_dimension="mass")
    cmp = view.intensity_comparison
    assert cmp.baseline_value == 0 and cmp.percent_change is None
    assert cmp.absolute_difference is not None and "zero" in cmp.percent_reason


def test_comparison_with_unavailable_baseline_explains_why(services):
    services.demo.load()
    cid = services.category_id("Electricity")
    view = services.analysis.compare(cid, None, JAN, APR, resource_dimension="energy", production_dimension="mass")
    assert view.intensity_comparison.status is CalcStatus.UNAVAILABLE
    assert view.prompts and "reliable intensity comparison" in view.prompts[-1]


def test_threshold_prompt_only_appears_when_configured_and_exceeded(services):
    services.demo.load()
    cid = services.category_id("Electricity")
    args = dict(resource_dimension="energy", production_dimension="mass")
    up = services.analysis.compare(cid, None, JAN, FEB, threshold_pct=D(10), **args)  # 1.5 -> 2.0 is +33%
    assert any("review threshold" in p for p in up.prompts)
    off = services.analysis.compare(cid, None, JAN, FEB, **args)
    assert not any("review threshold" in p for p in off.prompts)
    below = services.analysis.compare(cid, None, JAN, FEB, threshold_pct=D(50), **args)
    assert not any("review threshold" in p for p in below.prompts)


def test_trend_has_gaps_not_zeros_for_missing_periods(services):
    services.demo.load()
    cid = services.category_id("Electricity")
    trend = services.analysis.trend(cid, None, Period(date(2025, 1, 1), date(2025, 7, 31)),
                                    resource_dimension="energy", production_dimension="mass")
    by_month = {b.period.start.month: b for b in trend.buckets}
    assert by_month[1].intensity.value == D(2) and by_month[2].intensity.value == D("1.5")
    assert by_month[3].intensity.value is None and by_month[7].total is None
    assert trend.resource_unit == "kWh" and trend.production_unit == "kg"
    assert trend.overall.value is not None and trend.overall.status is CalcStatus.VALID_WITH_WARNINGS


def test_scenario_h_editing_a_source_record_updates_results(services):
    services.demo.load()
    rec = [r for r in services.resources.list() if r.reference == "DEMO-R-001"][0]
    services.resources.update(rec.id, ResourceRecordInput(rec.category_id, "1800", "kWh", "2025-01-01", "2025-01-31",
                                                          reference="DEMO-R-001"))
    (item,) = _find(services.analysis.overview(JAN).intensities, "Electricity")
    assert item.value == D(3)
    services.resources.delete(rec.id)
    assert _find(services.analysis.overview(JAN).resource_totals, "Electricity") == []


def test_editing_production_invalidates_a_previously_valid_indicator(services):
    services.demo.load()
    rec = [r for r in services.production.list() if r.reference == "DEMO-P-001"][0]
    services.production.update(rec.id, ProductionRecordInput("0", "kg", "2025-01-01", "2025-01-31", reference="DEMO-P-001"))
    (item,) = _find(services.analysis.overview(JAN).intensities, "Electricity")
    assert item.status is CalcStatus.UNAVAILABLE


def test_helper_listings(services):
    services.demo.load()
    cid = services.category_id("Electricity")
    assert services.analysis.scopes_for_category(cid) == [None, "demo-dyeing"]
    assert services.analysis.resource_dimensions(cid, None) == ["energy"]
    assert services.analysis.production_dimensions(None) == ["length", "mass"]
    quality = services.analysis.resource_quality()
    assert any(a.status == "review" for a in quality.values())
