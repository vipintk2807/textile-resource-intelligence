"""Data-quality assessment of stored records.

The assessment is derived on demand from the stored records (never stored), so it
cannot go stale when a record is edited or deleted.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from .calculations import merge_periods
from .errors import UnitError
from .types import Period, ProductionRecord, QualityAssessment, ResourceRecord
from .units import dimension_of


def _covers(merged: Sequence[Period], period: Period) -> bool:
    return any(block.contains(period) for block in merged)


def _positive_production_coverage(
    production: Iterable[ProductionRecord],
) -> dict[tuple[str | None, str], tuple[Period, ...]]:
    grouped: dict[tuple[str | None, str], list[Period]] = {}
    for record in production:
        if record.quantity <= 0:
            continue
        try:
            dimension = dimension_of(record.unit)
        except UnitError:
            continue
        grouped.setdefault((record.scope_key, dimension), []).append(record.period)
    return {key: merge_periods(periods) for key, periods in grouped.items()}


def _is_unknown_unit(unit: str) -> bool:
    try:
        dimension_of(unit)
    except UnitError:
        return True
    return False


def assess_resource_records(
    resources: Sequence[ResourceRecord],
    production: Sequence[ProductionRecord],
) -> dict[int, QualityAssessment]:
    """Quality status for every stored resource record, keyed by record id."""
    coverage = _positive_production_coverage(production)
    by_group: dict[tuple, list[ResourceRecord]] = {}
    for record in resources:
        by_group.setdefault((record.category_id, record.scope_key), []).append(record)

    result: dict[int, QualityAssessment] = {}
    for record in resources:
        if record.id is None:
            continue
        reasons: list[str] = []
        status = "valid"
        if _is_unknown_unit(record.unit):
            result[record.id] = QualityAssessment("invalid", ("Unknown unit; correct the record.",))
            continue
        covered = any(
            _covers(blocks, record.period)
            for (scope, _dim), blocks in coverage.items()
            if scope == record.scope_key
        )
        if not covered:
            scope = record.scope_key or "overall (no scope)"
            reasons.append(
                f"No positive production record covers this period for scope {scope}; "
                "intensity is unavailable."
            )
        siblings = by_group[(record.category_id, record.scope_key)]
        overlapping = [
            s.id
            for s in siblings
            if s.id != record.id and s.period != record.period and s.period.overlaps(record.period)
        ]
        if overlapping:
            reasons.append(
                "Overlaps record(s) "
                + ", ".join(str(i) for i in overlapping[:5])
                + " with a different interval; totals including both are unavailable."
            )
        same_event = [
            s.id
            for s in siblings
            if s.id != record.id
            and s.period == record.period
            and s.quantity == record.quantity
            and s.unit == record.unit
            and (s.reference is None or record.reference is None or s.reference == record.reference)
        ]
        if same_event:
            reasons.append(
                "Possible duplicate of record(s) "
                + ", ".join(str(i) for i in same_event[:5])
                + "; review before relying on totals."
            )
        if reasons:
            status = "review"
        result[record.id] = QualityAssessment(status, tuple(reasons))
    return result


def assess_production_records(
    production: Sequence[ProductionRecord],
) -> dict[int, QualityAssessment]:
    """Quality status for every stored production record, keyed by record id."""
    by_scope: dict[str | None, list[ProductionRecord]] = {}
    for record in production:
        by_scope.setdefault(record.scope_key, []).append(record)
    result: dict[int, QualityAssessment] = {}
    for record in production:
        if record.id is None:
            continue
        if _is_unknown_unit(record.unit):
            result[record.id] = QualityAssessment("invalid", ("Unknown unit; correct the record.",))
            continue
        reasons: list[str] = []
        if record.quantity == 0:
            reasons.append("Zero production is stored but cannot be used as an intensity denominator.")
        siblings = by_scope[record.scope_key]
        overlapping = [
            s.id
            for s in siblings
            if s.id != record.id
            and s.period != record.period
            and s.period.overlaps(record.period)
            and _same_dimension(s.unit, record.unit)
        ]
        if overlapping:
            reasons.append(
                "Overlaps record(s) "
                + ", ".join(str(i) for i in overlapping[:5])
                + " with a different interval; production totals including both are unavailable."
            )
        same_event = [
            s.id
            for s in siblings
            if s.id != record.id
            and s.period == record.period
            and s.quantity == record.quantity
            and s.unit == record.unit
            and (s.reference is None or record.reference is None or s.reference == record.reference)
        ]
        if same_event:
            reasons.append(
                "Possible duplicate of record(s) "
                + ", ".join(str(i) for i in same_event[:5])
                + "; review before relying on totals."
            )
        result[record.id] = QualityAssessment("review" if reasons else "valid", tuple(reasons))
    return result


def _same_dimension(a: str, b: str) -> bool:
    try:
        return dimension_of(a) == dimension_of(b)
    except UnitError:
        return False


def summarize(assessments: Mapping[int, QualityAssessment]) -> dict[str, int]:
    """Counts of records by quality status."""
    counts = {"valid": 0, "review": 0, "invalid": 0}
    for assessment in assessments.values():
        counts[assessment.status] = counts.get(assessment.status, 0) + 1
    return counts

