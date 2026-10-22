"""Production record workflows through the service layer."""

from decimal import Decimal as D

import pytest

from textile_resource_intelligence.exceptions import NotFound, ValidationFailed
from textile_resource_intelligence.schemas import ProductionRecordInput, RecordQuery


def _p(**kw):
    base = dict(quantity="600", unit="kg", period_start="2025-01-01", period_end="2025-01-31")
    base.update(kw)
    return ProductionRecordInput(**base)


def test_create_edit_delete_round_trip(services):
    rec = services.production.create(_p()).record
    assert services.production.get(rec.id).quantity == D(600)
    services.production.update(rec.id, _p(quantity="650", unit="tonne"))
    stored = services.production.get(rec.id)
    assert stored.quantity == D(650) and stored.unit == "tonne"
    services.production.delete(rec.id)
    assert services.production.list() == []
    with pytest.raises(NotFound):
        services.production.get(rec.id)


def test_zero_production_is_stored_but_negative_is_rejected(services):
    assert services.production.create(_p(quantity="0")).record.quantity == 0
    with pytest.raises(ValidationFailed):
        services.production.create(_p(quantity="-5", reference="neg"))


def test_missing_unit_and_resource_units_are_rejected(services):
    for bad in ({"unit": ""}, {"unit": "kWh"}, {"quantity": ""}, {"period_start": "x"}):
        with pytest.raises(ValidationFailed):
            services.production.create(_p(**bad))
    assert services.production.list() == []


def test_duplicate_reference_policy(services):
    services.production.create(_p(reference="B-1"))
    with pytest.raises(ValidationFailed):
        services.production.create(_p(reference="B-1"))
    # A record without a reference that matches an existing one is only *possibly* a duplicate.
    second = services.production.create(_p())
    third = services.production.create(_p())
    assert any(i.code == "possible_duplicate" for i in second.warnings)
    assert any(i.code == "possible_duplicate" for i in third.warnings)
    assert len(services.production.list()) == 3


def test_scope_and_period_filters(services):
    services.production.create(_p(scope_key="a"))
    services.production.create(_p(period_start="2025-02-01", period_end="2025-02-28"))
    assert len(services.production.list(RecordQuery(scope_mode="key", scope_key="a"))) == 1
    assert len(services.production.list(RecordQuery(scope_mode="overall"))) == 1
