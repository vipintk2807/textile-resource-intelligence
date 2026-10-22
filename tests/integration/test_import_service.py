"""CSV import: validation, duplicates, atomicity and equivalence with manual entry."""

from datetime import date
from decimal import Decimal as D

import pytest

from textile_resource_intelligence.exceptions import ImportFileError, RepositoryError
from textile_resource_intelligence.schemas import ImportLimits, ResourceRecordInput
from textile_resource_intelligence.services.import_service import suggest_mapping

HEADER = "resource_category,quantity,unit,period_start,period_end,scope_key,reference,notes\n"


def _csv(*rows: str, header: str = HEADER) -> bytes:
    return (header + "".join(r + "\n" for r in rows)).encode("utf-8")


def _run(services, content, kind="resource", dry_run=False, mapping=None):
    table = services.imports.inspect(content)
    mapping = mapping or suggest_mapping(table.columns, kind)
    return services.imports.run(content, kind, mapping, dry_run=dry_run)


def test_valid_file_is_imported_and_marked_as_import(services, fixture_dir):
    report = _run(services, (fixture_dir / "synthetic_resources.csv").read_bytes())
    assert report.committed and report.inserted == 4 and not report.errors
    records = services.resources.list()
    assert len(records) == 4 and all(r.source_type == "import" for r in records)
    first = records[0]
    assert first.quantity == D(1200) and first.unit == "kWh" and first.period.start == date(2025, 1, 1)


def test_production_file_is_imported(services, fixture_dir):
    report = _run(services, (fixture_dir / "synthetic_production.csv").read_bytes(), kind="production")
    assert report.committed and report.inserted == 2
    assert [r.quantity for r in services.production.list()] == [D(600), D(600)]


def test_dry_run_validates_without_writing(services, fixture_dir):
    report = _run(services, (fixture_dir / "synthetic_resources.csv").read_bytes(), dry_run=True)
    assert report.valid_rows == 4 and not report.committed and report.inserted == 0
    assert services.resources.list() == []


def test_invalid_rows_are_reported_by_row_and_field_and_nothing_is_committed(services, fixture_dir):
    report = _run(services, (fixture_dir / "invalid_import.csv").read_bytes())
    assert not report.committed and report.inserted == 0
    assert services.resources.list() == []  # the one valid row is NOT imported (all-or-nothing)
    by_row = {}
    for issue in report.errors:
        by_row.setdefault(issue.row, set()).add(issue.field)
    assert by_row == {2: {"quantity"}, 3: {"unit"}, 4: {"period_start"}, 5: {"resource_category"},
                      6: {"quantity"}, 7: {"record_type"}}
    assert report.rejected_rows == 6 and report.valid_rows == 1


def test_invalid_values_are_never_turned_into_zero(services):
    report = _run(services, _csv("Electricity,abc,kWh,2025-01-01,2025-01-31,,,"))
    assert report.rejected_rows == 1 and services.resources.list() == []


def test_missing_required_column_is_reported(services):
    content = b"resource_category,quantity,period_start\nElectricity,1,2025-01-01\n"
    table = services.imports.inspect(content)
    report = services.imports.run(content, "resource", suggest_mapping(table.columns, "resource"), dry_run=False)
    assert not report.committed and any(i.field == "unit" and i.code == "missing_column" for i in report.errors)


def test_extra_columns_are_ignored_and_listed(services):
    content = _csv("Electricity,10,kWh,2025-01-01,2025-01-31,,R1,n,", header=HEADER.strip() + ",unrelated\n")
    content = content.replace(b"n,\n", b"n,junk\n")
    report = _run(services, content)
    assert report.committed and report.ignored_columns == ("unrelated",)


def test_column_mapping_allows_different_header_names(services):
    content = b"Category,Amount,UOM,Start\nElectricity,10,kWh,2025-01-01\n"
    table = services.imports.inspect(content)
    mapping = suggest_mapping(table.columns, "resource")
    assert mapping["resource_category"] == "Category" and mapping["quantity"] == "Amount"
    assert _run(services, content, mapping=mapping).committed


def test_reimporting_the_same_file_skips_reference_duplicates(services, fixture_dir):
    content = (fixture_dir / "synthetic_resources.csv").read_bytes()
    _run(services, content)
    second = _run(services, content)
    assert second.skipped_duplicates == 4 and second.inserted == 0
    assert len(services.resources.list()) == 4


def test_duplicate_reference_inside_one_file_is_skipped_and_reported(services):
    report = _run(services, _csv("Electricity,10,kWh,2025-01-01,2025-01-31,,R1,",
                                 "Electricity,99,kWh,2025-01-01,2025-01-31,,R1,"))
    assert report.inserted == 1 and report.skipped_duplicates == 1
    assert any(i.code == "duplicate_skipped" and i.row == 2 for i in report.issues)


def test_rows_without_reference_that_look_alike_are_flagged_but_kept(services):
    row = "Electricity,10,kWh,2025-01-01,2025-01-31,,,"
    report = _run(services, _csv(row, row))
    assert report.inserted == 2 and report.rows_with_warnings == 1
    assert any(i.code == "possible_duplicate" for i in report.warnings)


def test_unit_not_permitted_for_category_is_rejected(services):
    report = _run(services, _csv("Electricity,10,L,2025-01-01,2025-01-31,,,"))
    assert report.rejected_rows == 1


def test_inactive_category_is_rejected(services):
    services.categories.set_active(services.category_id("Electricity"), False)
    report = _run(services, _csv("Electricity,10,kWh,2025-01-01,2025-01-31,,,"))
    assert report.rejected_rows == 1 and any(i.code == "inactive_category" for i in report.errors)


def test_empty_rows_are_counted_not_imported(services):
    report = _run(services, _csv("Electricity,10,kWh,2025-01-01,2025-01-31,,,", ",,,,,,,"))
    assert report.empty_rows == 1 and report.inserted == 1


@pytest.mark.parametrize("content,fragment", [
    (b"", "empty"),
    (b"   \n", "no data"),
    (b"a,b,c\n", "no data rows"),
    (b"\xff\xfe\x00bad", "binary"),
    (b"a,b\n\xe9,2\n", "UTF-8"),
    (b"a,a\n1,2\n", "more than once"),
    (b"a,b\n1,2,3,4\n", "Row 1 has 4 values"),
    (b"a,b\n1\n", "Row 1 has 1 values"),
    (b'a,b\n"1,2\n', "well-formed"),
])
def test_unreadable_files_raise_clear_errors(services, content, fragment):
    with pytest.raises(ImportFileError, match=fragment):
        services.imports.inspect(content)


def test_size_and_row_limits_are_enforced(uow_factory):
    from tests.conftest import build_services
    small = build_services(uow_factory, ImportLimits(max_bytes=50, max_rows=2))
    with pytest.raises(ImportFileError, match="limit"):
        small.imports.inspect(b"a,b\n" + b"1,2\n" * 30)
    rows = build_services(uow_factory, ImportLimits(max_bytes=10_000, max_rows=2))
    with pytest.raises(ImportFileError, match="limit"):
        rows.imports.inspect(b"a,b\n1,2\n3,4\n5,6\n")


def test_utf8_bom_from_excel_is_handled(services):
    content = "\ufeff".encode("utf-8") + _csv("Electricity,10,kWh,2025-01-01,2025-01-31,,,")
    assert _run(services, content).committed


def test_failure_while_writing_rolls_back_the_whole_import(memory_state):
    from tests.conftest import build_services
    from tests.support.memory_repository import make_memory_uow
    from textile_resource_intelligence.services.category_service import seed_initial_categories

    uow = make_memory_uow(memory_state)
    with uow() as repo:
        seed_initial_categories(repo)
    services = build_services(uow)
    memory_state.fail_on_resource_insert_number = 3
    content = _csv("Electricity,1,kWh,2025-01-01,2025-01-31,,A,", "Electricity,2,kWh,2025-02-01,2025-02-28,,B,",
                   "Electricity,3,kWh,2025-03-01,2025-03-31,,C,")
    with pytest.raises(RepositoryError):
        _run(services, content)
    assert services.resources.list() == []  # nothing partially committed


def test_imported_data_matches_equivalent_manual_entry(services, fixture_dir):
    _run(services, (fixture_dir / "synthetic_resources.csv").read_bytes())
    key = lambda r: (r.category_id, r.quantity, r.unit, r.period)  # noqa: E731
    imported = sorted(map(key, services.resources.list()))
    for rec in services.resources.list():
        services.resources.delete(rec.id)
    for cat, qty, unit, start, end in [("Electricity", "1200", "kWh", "2025-01-01", "2025-01-31"),
                                       ("Water", "3000", "L", "2025-01-01", "2025-01-31"),
                                       ("Electricity", "900", "kWh", "2025-02-01", "2025-02-28"),
                                       ("Water", "2400", "L", "2025-02-01", "2025-02-28")]:
        services.resources.create(ResourceRecordInput(services.category_id(cat), qty, unit, start, end))
    assert sorted(map(key, services.resources.list())) == imported


def test_suggest_mapping_is_case_and_space_tolerant():
    mapping = suggest_mapping(["Resource Category", "QUANTITY", "Unit", "Period-Start"], "resource")
    assert mapping["resource_category"] == "Resource Category" and mapping["period_start"] == "Period-Start"
    assert mapping["period_end"] is None


def test_template_has_every_importable_column_and_imports_cleanly_when_filled():
    from textile_resource_intelligence.services.import_service import fields_for, template_csv
    for kind in ("resource", "production"):
        text = template_csv(kind).decode("utf-8-sig")
        assert text.strip().split(",") == [name for name, _ in fields_for(kind)]
