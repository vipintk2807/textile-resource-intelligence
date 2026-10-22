"""Clearly labelled synthetic demonstration data.

Every demo record has ``source_type='demo'`` and a ``DEMO-`` reference so it is always
distinguishable from real data and can be removed in one step. The values are
artificial test values chosen to exercise specific behaviours; they do not describe
any real factory and are not benchmarks.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.types import Issue
from ..domain.validation import validate_record_fields
from ..exceptions import ValidationFailed
from ..schemas import ProductionDraft, ResourceDraft
from .ports import UnitOfWorkFactory

SYNTHETIC_NOTE = "Synthetic demonstration data - not real factory data."


@dataclass(frozen=True)
class _R:
    category: str
    quantity: str
    unit: str
    start: str
    end: str
    ref: str
    scope: str | None = None


@dataclass(frozen=True)
class _P:
    quantity: str
    unit: str
    start: str
    end: str
    ref: str
    scope: str | None = None


DEMO_RESOURCES = (
    # Jan/Feb: matching production -> 2 and 1.5 kWh/kg, 5 and 4 L/kg (overall 1.75 and 4.5)
    _R("Electricity", "1200", "kWh", "2025-01-01", "2025-01-31", "DEMO-R-001"),
    _R("Water", "3000", "L", "2025-01-01", "2025-01-31", "DEMO-R-002"),
    _R("Electricity", "900", "kWh", "2025-02-01", "2025-02-28", "DEMO-R-003"),
    _R("Water", "2400", "L", "2025-02-01", "2025-02-28", "DEMO-R-004"),
    # March: consumption but no production record -> intensity unavailable
    _R("Electricity", "1000", "kWh", "2025-03-01", "2025-03-31", "DEMO-R-005"),
    _R("Water", "2500", "L", "2025-03-01", "2025-03-31", "DEMO-R-006"),
    # April: production recorded as zero -> intensity unavailable
    _R("Electricity", "800", "kWh", "2025-04-01", "2025-04-30", "DEMO-R-007"),
    # May: consumption covers only the first 15 days, production the whole month
    _R("Electricity", "500", "kWh", "2025-05-01", "2025-05-15", "DEMO-R-008"),
    # June: MWh converted to kWh before dividing (1.1 MWh / 550 kg = 2 kWh/kg)
    _R("Electricity", "1.1", "MWh", "2025-06-01", "2025-06-30", "DEMO-R-009"),
    # Waste: recorded zero in January -> zero baseline, percentage change unavailable
    _R("Waste", "0", "kg", "2025-01-01", "2025-01-31", "DEMO-R-010"),
    _R("Waste", "20", "kg", "2025-02-01", "2025-02-28", "DEMO-R-011"),
    # Chemicals in two dimensions: totals stay separate (kg vs L)
    _R("Chemicals", "50", "kg", "2025-01-01", "2025-01-31", "DEMO-R-012"),
    _R("Chemicals", "20", "L", "2025-01-01", "2025-01-31", "DEMO-R-013"),
    # Fuel: two identical records without references -> possible duplicate warning
    _R("Fuel", "100", "L", "2025-01-10", "2025-01-10", ""),
    _R("Fuel", "100", "L", "2025-01-10", "2025-01-10", ""),
    # A separate scope with its own production
    _R("Electricity", "500", "kWh", "2025-01-01", "2025-01-31", "DEMO-R-014", "demo-dyeing"),
    _R("Electricity", "480", "kWh", "2025-02-01", "2025-02-28", "DEMO-R-015", "demo-dyeing"),
)

DEMO_PRODUCTION = (
    _P("600", "kg", "2025-01-01", "2025-01-31", "DEMO-P-001"),
    _P("600", "kg", "2025-02-01", "2025-02-28", "DEMO-P-002"),
    _P("0", "kg", "2025-04-01", "2025-04-30", "DEMO-P-003"),
    _P("600", "kg", "2025-05-01", "2025-05-31", "DEMO-P-004"),
    _P("550", "kg", "2025-06-01", "2025-06-30", "DEMO-P-005"),
    # Length-based production for February: metres are never added to kilograms
    _P("3000", "m", "2025-02-01", "2025-02-28", "DEMO-P-006"),
    _P("400", "kg", "2025-01-01", "2025-01-31", "DEMO-P-007", "demo-dyeing"),
    _P("400", "kg", "2025-02-01", "2025-02-28", "DEMO-P-008", "demo-dyeing"),
)


class DemoService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow = uow_factory

    def load(self) -> tuple[int, int]:
        """Insert the synthetic dataset in one transaction; returns (resource, production) counts."""
        with self._uow() as repo:
            if repo.count_records().demo_total > 0:
                raise ValidationFailed([Issue("demo", "already_loaded",
                                              "Synthetic demonstration data is already loaded.")])
            categories = {c.name.casefold(): c for c in repo.list_categories()}
            for row in DEMO_RESOURCES:
                category = categories.get(row.category.casefold())
                if category is None or not category.is_active:
                    raise ValidationFailed([Issue("demo", "missing_category",
                        f"The demo data needs an active category named '{row.category}'.")])
                fields, issues = validate_record_fields(
                    "resource", quantity=row.quantity, unit=row.unit, period_start=row.start,
                    period_end=row.end, scope_key=row.scope, reference=row.ref or None,
                    notes=SYNTHETIC_NOTE, allowed_units=list(category.allowed_units))
                if fields is None:
                    raise ValidationFailed(issues)
                assert category.id is not None
                repo.add_resource_record(ResourceDraft(category.id, fields, "demo"))
            for prow in DEMO_PRODUCTION:
                fields, issues = validate_record_fields(
                    "production", quantity=prow.quantity, unit=prow.unit, period_start=prow.start,
                    period_end=prow.end, scope_key=prow.scope, reference=prow.ref, notes=SYNTHETIC_NOTE)
                if fields is None:
                    raise ValidationFailed(issues)
                repo.add_production_record(ProductionDraft(fields, "demo"))
        return len(DEMO_RESOURCES), len(DEMO_PRODUCTION)

    def remove(self) -> tuple[int, int]:
        """Delete only synthetic demo records; real records are never touched."""
        with self._uow() as repo:
            return repo.delete_records_by_source("demo")
