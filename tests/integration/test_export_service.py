"""CSV export: columns, units, context, formula-injection protection, re-import."""

import csv
import io
from datetime import date
from decimal import Decimal as D

from textile_resource_intelligence.domain.types import Period
from textile_resource_intelligence.schemas import ProductionRecordInput, RecordQuery, ResourceRecordInput
from textile_resource_intelligence.services.export_service import dataframe_to_csv_bytes, sanitize_cell
from textile_resource_intelligence.services.import_service import suggest_mapping

JAN = Period(date(2025, 1, 1), date(2025, 1, 31))


def _read(result):
    text = result.content.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


def _seed(services):
    e = services.category_id("Electricity")
    services.resources.create(ResourceRecordInput(e, "1200", "kWh", "2025-01-01", "2025-01-31", reference="R1"))
    services.production.create(ProductionRecordInput("600", "kg", "2025-01-01", "2025-01-31", reference="P1"))


def test_resource_export_keeps_quantity_unit_and_period(services):
    _seed(services)
    result = services.exports.resource_records()
    row = _read(result)[0]
    assert result.rows == 1 and row["quantity"] == "1200" and row["unit"] == "kWh"
    assert row["period_start"] == "2025-01-01" and row["period_end"] == "2025-01-31"
    assert row["resource_category"] == "Electricity" and row["data_origin"] == "user-entered or imported"
    assert result.filename.startswith("resource_records_") and result.filename.endswith(".csv")


def test_cubic_metres_are_exported_with_a_readable_unit(services):
    services.resources.create(ResourceRecordInput(services.category_id("Water"), "2.5", "m3", "2025-01-01"))
    assert _read(services.exports.resource_records())[0]["unit"] == "m³"


def test_source_export_can_be_read_back_by_the_importer(services):
    _seed(services)
    content = services.exports.resource_records().content
    for rec in services.resources.list():
        services.resources.delete(rec.id)
    table = services.imports.inspect(content)
    report = services.imports.run(content, "resource", suggest_mapping(table.columns, "resource"), dry_run=False)
    assert report.committed and services.resources.list()[0].quantity == D(1200)


def test_intensity_export_contains_numerator_denominator_units_and_period(services):
    _seed(services)
    result = services.exports.intensities(JAN)
    row = _read(result)[0]
    assert row["intensity"] == "2" and row["intensity_unit"] == "kWh/kg"
    assert row["resource_total"] == "1200" and row["production_total"] == "600"
    assert row["resource_unit"] == "kWh" and row["production_unit"] == "kg"
    assert row["report_period_start"] == "2025-01-01" and row["status"] == "valid"


def test_unavailable_intensity_is_exported_empty_not_zero(services):
    services.resources.create(ResourceRecordInput(services.category_id("Electricity"), "1200", "kWh",
                                                  "2025-01-01", "2025-01-31"))
    services.production.create(ProductionRecordInput("0", "kg", "2025-01-01", "2025-01-31"))
    row = _read(services.exports.intensities(JAN))[0]
    assert row["intensity"] == "" and row["status"] == "unavailable" and "zero" in row["reason_or_warnings"]


def test_totals_export_reports_coverage(services):
    _seed(services)
    row = _read(services.exports.resource_summaries(JAN))[0]
    assert row["total_quantity"] == "1200" and row["days_covered"] == "31" and row["days_in_period"] == "31"


def test_exported_intensity_matches_the_analysis_service(services):
    _seed(services)
    overview = services.analysis.overview(JAN)
    row = _read(services.exports.intensities(JAN))[0]
    assert D(row["intensity"]) == overview.intensities[0].value


def test_no_matching_data_gives_zero_rows(services):
    assert services.exports.resource_records(RecordQuery(source_type="import")).rows == 0
    assert services.exports.intensities(JAN).rows == 0


def test_formula_like_text_is_neutralised_in_exports(services):
    e = services.category_id("Electricity")
    services.resources.create(ResourceRecordInput(e, "5", "kWh", "2025-01-01", reference="=HYPERLINK(1)", notes="@cmd"))
    row = _read(services.exports.resource_records())[0]
    assert row["reference"] == "'=HYPERLINK(1)" and row["notes"] == "'@cmd"


def test_sanitiser_only_touches_formula_text():
    assert sanitize_cell("=SUM(A1)") == "'=SUM(A1)"
    assert sanitize_cell("+1") == "'+1" and sanitize_cell("-1") == "'-1" and sanitize_cell("\tx") == "'\tx"
    assert sanitize_cell("Dyeing line") == "Dyeing line" and sanitize_cell("") == ""
    assert sanitize_cell(-10.5) == -10.5 and sanitize_cell(None) is None


def test_numeric_columns_are_not_altered_by_sanitising():
    import pandas as pd
    frame = pd.DataFrame({"percent_change": ["-10.5"], "notes": ["-note"]})
    text = dataframe_to_csv_bytes(frame, ["percent_change"]).decode("utf-8-sig")
    assert "-10.5" in text and "'-note" in text and "'-10.5" not in text


def test_demo_records_are_labelled_in_exports(services):
    services.demo.load()
    rows = _read(services.exports.resource_records())
    assert {r["data_origin"] for r in rows} == {"synthetic demonstration data"}
    totals = _read(services.exports.resource_summaries(Period(date(2025, 1, 1), date(2025, 1, 31))))
    assert all(r["includes_synthetic_demo_records"] == "True" for r in totals)
