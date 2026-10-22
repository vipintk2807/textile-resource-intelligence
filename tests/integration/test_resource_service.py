"""Resource record workflows through the service layer (memory and SQLite)."""

from datetime import date
from decimal import Decimal as D

import pytest

from textile_resource_intelligence.exceptions import NotFound, ValidationFailed
from textile_resource_intelligence.schemas import CategoryInput, RecordQuery, ResourceRecordInput


def _input(services, **kw):
    base = dict(resource_category_id=services.category_id("Electricity"), quantity="1200", unit="kWh",
                period_start="2025-01-01", period_end="2025-01-31")
    base.update(kw)
    return ResourceRecordInput(**base)


def test_create_stores_original_quantity_and_unit(services):
    result = services.resources.create(_input(services, quantity="1.2", unit="MWh"))
    stored = services.resources.get(result.record.id)
    assert stored.quantity == D("1.2") and stored.unit == "MWh"
    assert stored.period.start == date(2025, 1, 1) and stored.source_type == "manual"


def test_invalid_record_is_not_saved(services):
    with pytest.raises(ValidationFailed) as err:
        services.resources.create(_input(services, quantity="abc"))
    assert any(i.field == "quantity" for i in err.value.issues)
    assert services.resources.list() == []


def test_unit_must_be_permitted_for_the_category(services):
    with pytest.raises(ValidationFailed) as err:
        services.resources.create(_input(services, unit="L"))
    assert any(i.field == "unit" for i in err.value.issues)


def test_missing_category_is_reported(services):
    with pytest.raises(ValidationFailed) as err:
        services.resources.create(_input(services, resource_category_id=None))
    assert any(i.field == "resource_category_id" for i in err.value.issues)


def test_negative_and_meter_reading_records_are_rejected(services):
    for kwargs in ({"quantity": "-1"}, {"record_type": "meter_reading"}):
        with pytest.raises(ValidationFailed):
            services.resources.create(_input(services, **kwargs))


def test_edit_revalidates_and_changes_the_stored_values(services):
    rec = services.resources.create(_input(services)).record
    services.resources.update(rec.id, _input(services, quantity="1300"))
    assert services.resources.get(rec.id).quantity == D("1300")
    with pytest.raises(ValidationFailed):
        services.resources.update(rec.id, _input(services, quantity="-1"))
    assert services.resources.get(rec.id).quantity == D("1300")


def test_delete_removes_the_record_and_missing_ids_raise(services):
    rec = services.resources.create(_input(services)).record
    services.resources.delete(rec.id)
    assert services.resources.list() == []
    with pytest.raises(NotFound):
        services.resources.delete(rec.id)
    with pytest.raises(NotFound):
        services.resources.update(rec.id, _input(services))


def test_same_reference_scope_and_period_is_a_reliable_duplicate(services):
    services.resources.create(_input(services, reference="M-1"))
    with pytest.raises(ValidationFailed) as err:
        services.resources.create(_input(services, reference="M-1", quantity="5"))
    assert any(i.code == "duplicate_reference" for i in err.value.issues)
    assert len(services.resources.list()) == 1


def test_same_reference_in_another_period_is_allowed(services):
    services.resources.create(_input(services, reference="M-1"))
    services.resources.create(_input(services, reference="M-1", period_start="2025-02-01", period_end="2025-02-28"))
    assert len(services.resources.list()) == 2


def test_identical_records_without_reference_are_kept_with_a_warning(services):
    services.resources.create(_input(services))
    second = services.resources.create(_input(services))
    assert any(i.code == "possible_duplicate" for i in second.warnings)
    assert len(services.resources.list()) == 2


def test_editing_a_record_does_not_flag_it_as_its_own_duplicate(services):
    rec = services.resources.create(_input(services, reference="M-1")).record
    services.resources.update(rec.id, _input(services, reference="M-1", notes="corrected"))


def test_filters_work_together(services):
    e, w = services.category_id("Electricity"), services.category_id("Water")
    services.resources.create(_input(services, scope_key="a"))
    services.resources.create(_input(services, period_start="2025-02-01", period_end="2025-02-28"))
    services.resources.create(ResourceRecordInput(w, "10", "L", "2025-01-05"))
    assert len(services.resources.list(RecordQuery(category_id=e))) == 2
    assert len(services.resources.list(RecordQuery(category_id=e, scope_mode="key", scope_key="a"))) == 1
    assert len(services.resources.list(RecordQuery(scope_mode="overall"))) == 2
    assert len(services.resources.list(RecordQuery(date_from=date(2025, 2, 1), date_to=date(2025, 2, 28)))) == 1
    assert len(services.resources.list(RecordQuery(source_type="import"))) == 0
    services.resources.create(_input(services, scope_key="zz", reference="FindMe", notes="hello"))
    assert len(services.resources.list(RecordQuery(text="findme"))) == 1


def test_inactive_category_rejects_new_records_but_keeps_history(services):
    services.resources.create(_input(services))
    services.categories.set_active(services.category_id("Electricity"), False)
    with pytest.raises(ValidationFailed):
        services.resources.create(_input(services, quantity="5"))
    assert len(services.resources.list()) == 1


def test_renaming_a_category_keeps_records_linked(services):
    cid = services.category_id("Electricity")
    rec = services.resources.create(_input(services)).record
    services.categories.update(cid, CategoryInput("Grid electricity", "electricity", "kWh", ["kWh", "MWh"]), is_active=True)
    assert services.resources.get(rec.id).category_id == cid
    assert services.categories.get(cid).name == "Grid electricity"


def test_removing_a_permitted_unit_does_not_invalidate_existing_records(services):
    cid = services.category_id("Electricity")
    rec = services.resources.create(_input(services, unit="MWh", quantity="1")).record
    services.categories.update(cid, CategoryInput("Electricity", "electricity", "kWh", ["kWh"]), is_active=True)
    services.resources.update(rec.id, _input(services, unit="MWh", quantity="2"))  # historical unit still editable
    assert services.resources.get(rec.id).unit == "MWh"
    with pytest.raises(ValidationFailed):
        services.resources.create(_input(services, unit="MWh", reference="new"))


def test_category_rules(services):
    with pytest.raises(ValidationFailed):
        services.categories.create(CategoryInput("electricity", "electricity", "kWh", ["kWh"]))  # duplicate, case-insensitive
    created = services.categories.create(CategoryInput("Dye A", "chemicals", "kg", ["kg", "g"]))
    assert created.id and created.is_active
    services.resources.create(ResourceRecordInput(created.id, "5", "kg", "2025-01-01"))
    with pytest.raises(ValidationFailed) as err:
        services.categories.update(created.id, CategoryInput("Dye A", "water", "L", ["L"]), is_active=True)
    assert any(i.code == "type_locked" for i in err.value.issues)
