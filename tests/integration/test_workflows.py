"""End-to-end workflows required by the testing document (section 15) plus demo data rules."""

from datetime import date
from decimal import Decimal as D

import pytest

from textile_resource_intelligence.domain.types import Period
from textile_resource_intelligence.exceptions import ValidationFailed
from textile_resource_intelligence.schemas import ProductionRecordInput, ResourceRecordInput
from textile_resource_intelligence.services.import_service import suggest_mapping

JAN = Period(date(2025, 1, 1), date(2025, 1, 31))
JAN_FEB = Period(date(2025, 1, 1), date(2025, 2, 28))


def test_record_to_analysis_to_export(services):
    services.resources.create(ResourceRecordInput(services.category_id("Electricity"), "1.2", "MWh",
                                                  "2025-01-01", "2025-01-31"))
    services.production.create(ProductionRecordInput("600", "kg", "2025-01-01", "2025-01-31"))
    (item,) = services.analysis.overview(JAN).intensities
    assert item.value == D(2)
    exported = services.exports.intensities(JAN).content.decode("utf-8-sig")
    assert ",2,kWh/kg," in exported  # exported value equals the calculation


def test_csv_to_analysis_to_export(services, fixture_dir):
    for name, kind in (("synthetic_resources.csv", "resource"), ("synthetic_production.csv", "production")):
        content = (fixture_dir / name).read_bytes()
        table = services.imports.inspect(content)
        assert services.imports.run(content, kind, suggest_mapping(table.columns, kind), dry_run=False).committed
    overview = services.analysis.overview(JAN_FEB)
    values = {i.category_name: i.value for i in overview.intensities}
    assert values == {"Electricity": D("1.75"), "Water": D("4.5")}
    assert services.exports.intensities(JAN_FEB).rows == 2


def test_failed_import_leaves_existing_data_intact_and_can_be_retried(services, fixture_dir):
    services.resources.create(ResourceRecordInput(services.category_id("Electricity"), "5", "kWh", "2024-12-01"))
    bad = (fixture_dir / "invalid_import.csv").read_bytes()
    table = services.imports.inspect(bad)
    report = services.imports.run(bad, "resource", suggest_mapping(table.columns, "resource"), dry_run=False)
    assert not report.committed and len(services.resources.list()) == 1
    good = (fixture_dir / "synthetic_resources.csv").read_bytes()
    table = services.imports.inspect(good)
    assert services.imports.run(good, "resource", suggest_mapping(table.columns, "resource"), dry_run=False).committed
    assert len(services.resources.list()) == 5


def test_demo_data_is_explicit_labelled_and_removable(services):
    assert services.resources.list() == []  # nothing is pre-loaded
    counts = services.demo.load()
    assert counts == (17, 8)
    records = services.resources.list() + services.production.list()
    assert all(r.source_type == "demo" and "Synthetic" in r.notes for r in records)
    with pytest.raises(ValidationFailed):
        services.demo.load()
    services.resources.create(ResourceRecordInput(services.category_id("Water"), "7", "L", "2025-09-01"))
    removed = services.demo.remove()
    assert removed == (17, 8)
    remaining = services.resources.list()
    assert len(remaining) == 1 and remaining[0].source_type == "manual"


def test_preferences_round_trip_and_validation(services):
    defaults = services.preferences.get()
    assert defaults.default_period_mode == "month" and defaults.intensity_threshold_pct is None
    saved = services.preferences.save(default_period_mode="range", intensity_threshold_pct="12.5", display_decimals=3)
    assert saved.default_period_mode == "range" and saved.intensity_threshold_pct == D("12.5")
    assert services.preferences.get().display_decimals == 3
    assert services.preferences.save(default_period_mode="day", intensity_threshold_pct="", display_decimals=2) \
        .intensity_threshold_pct is None
    for bad in ({"default_period_mode": "week"}, {"intensity_threshold_pct": "-5"},
                {"intensity_threshold_pct": "abc"}, {"display_decimals": 9}):
        args = dict(default_period_mode="month", intensity_threshold_pct="", display_decimals=2)
        args.update(bad)
        with pytest.raises(ValidationFailed):
            services.preferences.save(**args)


def test_repeated_calculations_are_consistent(services):
    services.demo.load()
    first = services.analysis.overview(JAN_FEB)
    second = services.analysis.overview(JAN_FEB)
    assert [(i.category_name, i.value) for i in first.intensities] == [(i.category_name, i.value) for i in second.intensities]


def test_failed_demo_load_commits_nothing(services):
    services.categories.set_active(services.category_id("Fuel"), False)
    with pytest.raises(ValidationFailed):
        services.demo.load()
    assert services.resources.list() == [] and services.production.list() == []
