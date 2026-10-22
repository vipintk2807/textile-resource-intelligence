"""Authoritative calculations: aggregation, intensity and period bucketing.

Rules implemented here (see the calculation specification):

* Records are summed only inside one resource category, one scope key and one
  physical dimension, after explicit unit conversion.
* Only records that lie entirely inside the reporting window are counted. A record
  that straddles the window boundary is never pro-rated; the total is flagged.
* Records with different but overlapping intervals could double count, so the total
  becomes unavailable. Records with identical intervals are separate events.
* Intensity is total resource / total production over the *same* window and scope;
  the denominator must be positive. Missing data is never treated as zero.
* Overall intensity over several periods is sum(C) / sum(P), never a mean of ratios.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import Protocol

from .errors import CalculationUnavailableError, DomainError, QuantityError, UnitError
from .numbers import CTX, parse_decimal
from .types import (
    CalcStatus,
    CalculationResult,
    Category,
    IntensityResult,
    Period,
    ProductionRecord,
    ResourceRecord,
)
from .units import (
    CANONICAL_UNITS,
    DIMENSION_LABELS,
    canonical_unit_for,
    convert_quantity,
    dimension_of,
)

MAX_BUCKETS = 400


class _Record(Protocol):
    id: int | None
    quantity: Decimal
    unit: str
    period: Period
    scope_key: str | None
    source_type: str


# --------------------------------------------------------------------------- scalars
def calculate_intensity(resource_quantity: object, production_quantity: object) -> Decimal:
    """Resource quantity divided by production quantity (``I = C / P``).

    Raises CalculationUnavailableError when an input is missing or invalid or when
    production is not strictly positive. No value is ever substituted for zero.
    """
    if resource_quantity is None:
        raise CalculationUnavailableError("Intensity unavailable: the resource quantity is missing.")
    if production_quantity is None:
        raise CalculationUnavailableError("Intensity unavailable: the production quantity is missing.")
    try:
        resource = parse_decimal(resource_quantity, label="Resource quantity", enforce_limits=False)
        production = parse_decimal(production_quantity, label="Production quantity", enforce_limits=False)
    except QuantityError as exc:
        raise CalculationUnavailableError(f"Intensity unavailable: {exc}") from exc
    if resource < 0:
        raise CalculationUnavailableError("Intensity unavailable: the resource quantity is negative.")
    if production == 0:
        raise CalculationUnavailableError("Intensity unavailable: production quantity is zero.")
    if production < 0:
        raise CalculationUnavailableError("Intensity unavailable: production quantity is negative.")
    return CTX.divide(resource, production)


def calculate_percentage_change(current_value: object, baseline_value: object) -> Decimal:
    """``(current - baseline) / baseline * 100`` for a positive baseline."""
    if current_value is None or baseline_value is None:
        raise CalculationUnavailableError("Percentage change unavailable: a value is missing.")
    try:
        current = parse_decimal(current_value, label="Current value", enforce_limits=False)
        baseline = parse_decimal(baseline_value, label="Baseline value", enforce_limits=False)
    except QuantityError as exc:
        raise CalculationUnavailableError(f"Percentage change unavailable: {exc}") from exc
    if baseline == 0:
        raise CalculationUnavailableError("Percentage change unavailable: baseline value is zero.")
    if baseline < 0 or current < 0:
        raise CalculationUnavailableError("Percentage change unavailable: negative values are not comparable.")
    return CTX.multiply(CTX.divide(CTX.subtract(current, baseline), baseline), Decimal(100))


# --------------------------------------------------------------------------- periods
def merge_periods(periods: Iterable[Period]) -> tuple[Period, ...]:
    """Union of intervals; overlapping or adjacent days are merged."""
    ordered = sorted(periods)
    merged: list[Period] = []
    for period in ordered:
        if merged and period.start <= merged[-1].end + timedelta(days=1):
            if period.end > merged[-1].end:
                merged[-1] = Period(merged[-1].start, period.end)
        else:
            merged.append(period)
    return tuple(merged)


def total_days(periods: Iterable[Period]) -> int:
    """Number of calendar days covered by already-merged periods."""
    return sum(p.days for p in periods)


def make_buckets(window: Period, granularity: str) -> list[Period]:
    """Split ``window`` into day or calendar-month buckets (clipped to the window)."""
    if granularity not in {"day", "month"}:
        raise ValueError("granularity must be 'day' or 'month'")
    buckets: list[Period] = []
    if granularity == "day":
        if window.days > MAX_BUCKETS:
            raise ValueError(
                f"A daily view supports at most {MAX_BUCKETS} days; choose a shorter range or monthly view."
            )
        current = window.start
        while current <= window.end:
            buckets.append(Period(current, current))
            current += timedelta(days=1)
        return buckets
    current = window.start
    while current <= window.end:
        if current.month == 12:
            next_month = date(current.year + 1, 1, 1)
        else:
            next_month = date(current.year, current.month + 1, 1)
        end = min(next_month - timedelta(days=1), window.end)
        buckets.append(Period(current, end))
        if len(buckets) > MAX_BUCKETS:
            raise ValueError(f"The selected range has more than {MAX_BUCKETS} periods.")
        current = next_month
    return buckets


# ------------------------------------------------------------------------ aggregation
def _ids(records: Iterable[_Record]) -> tuple[int, ...]:
    return tuple(sorted(r.id for r in records if r.id is not None))


def _find_overlap_conflicts(records: Sequence[_Record]) -> tuple[int, ...]:
    """Ids of records whose intervals overlap another, *different* interval."""
    by_period: dict[Period, list[_Record]] = {}
    for record in records:
        by_period.setdefault(record.period, []).append(record)
    distinct = sorted(by_period)
    conflicted: set[Period] = set()
    for i, first in enumerate(distinct):
        for second in distinct[i + 1 :]:
            if second.start > first.end:
                break
            conflicted.add(first)
            conflicted.add(second)
    return _ids(r for p in conflicted for r in by_period[p])


def _aggregate_group(
    records: Sequence[_Record],
    window: Period,
    *,
    calculation: str,
    scope_key: str | None,
    dimension: str,
    target_unit: str,
    noun: str,
    category_id: int | None = None,
    category_name: str | None = None,
) -> CalculationResult:
    inside = [r for r in records if window.contains(r.period)]
    straddling = [r for r in records if not window.contains(r.period)]

    def unavailable(reason: str) -> CalculationResult:
        return CalculationResult(
            calculation=calculation,
            status=CalcStatus.UNAVAILABLE,
            window=window,
            scope_key=scope_key,
            dimension=dimension,
            category_id=category_id,
            category_name=category_name,
            unit=target_unit,
            record_ids=_ids(records),
            record_count=len(records),
            source_types=frozenset(r.source_type for r in records),
            reason=reason,
        )

    if not inside:
        return unavailable(
            f"{len(straddling)} record(s) span the boundary of the selected period and cannot be "
            f"split. Select a period that contains whole {noun} records."
        )
    conflicts = _find_overlap_conflicts(inside)
    if conflicts:
        shown = ", ".join(str(i) for i in conflicts[:10])
        return unavailable(
            f"{noun.capitalize()} records with overlapping but different intervals (ids {shown}) could "
            "be counted twice. Correct their periods before a total can be calculated."
        )

    total = Decimal(0)
    for record in inside:
        total = CTX.add(total, convert_quantity(record.quantity, record.unit, target_unit))

    coverage = merge_periods(r.period for r in inside)
    covered = total_days(coverage)
    warnings: list[str] = []
    if straddling:
        warnings.append(
            f"{len(straddling)} {noun} record(s) span the period boundary and were excluded; the "
            "total is partial."
        )
    if covered < window.days:
        warnings.append(
            f"Records cover {covered} of {window.days} days in this period; the total may be incomplete."
        )
    return CalculationResult(
        calculation=calculation,
        status=CalcStatus.VALID_WITH_WARNINGS if warnings else CalcStatus.VALID,
        window=window,
        scope_key=scope_key,
        dimension=dimension,
        category_id=category_id,
        category_name=category_name,
        value=total,
        unit=target_unit,
        record_ids=_ids(inside),
        record_count=len(inside),
        source_types=frozenset(r.source_type for r in inside),
        coverage=coverage,
        coverage_days=covered,
        warnings=tuple(warnings),
    )


def _sort_key(key: tuple) -> tuple:
    return tuple("" if part is None else part for part in key)


def aggregate_resources(
    records: Iterable[ResourceRecord],
    window: Period,
    categories: Mapping[int, Category],
) -> list[CalculationResult]:
    """Resource totals per (category, scope, dimension) for ``window``.

    Different categories, scopes and physical dimensions are never combined.
    Records outside the window are ignored; records with unknown units make the
    affected category/scope unavailable instead of being dropped silently.
    """
    groups: dict[tuple[int, str | None, str], list[ResourceRecord]] = {}
    unknown: dict[tuple[int, str | None], list[ResourceRecord]] = {}
    for record in records:
        if not record.period.overlaps(window):
            continue
        try:
            dimension = dimension_of(record.unit)
        except UnitError:
            unknown.setdefault((record.category_id, record.scope_key), []).append(record)
            continue
        groups.setdefault((record.category_id, record.scope_key, dimension), []).append(record)

    results: list[CalculationResult] = []
    for key in sorted(groups, key=_sort_key):
        category_id, scope_key, dimension = key
        category = categories.get(category_id)
        preferred = category.default_unit if category else None
        if preferred and _safe_dimension(preferred) == dimension:
            target = preferred
        else:
            target = canonical_unit_for(dimension)
        results.append(
            _aggregate_group(
                groups[key],
                window,
                calculation="resource_total",
                scope_key=scope_key,
                dimension=dimension,
                target_unit=target,
                noun="consumption",
                category_id=category_id,
                category_name=category.name if category else f"Category {category_id}",
            )
        )
    for (category_id, scope_key), bad in sorted(unknown.items(), key=lambda kv: _sort_key(kv[0])):
        category = categories.get(category_id)
        ids = ", ".join(str(i) for i in _ids(bad))
        results.append(
            CalculationResult(
                calculation="resource_total",
                status=CalcStatus.UNAVAILABLE,
                window=window,
                scope_key=scope_key,
                dimension="unknown",
                category_id=category_id,
                category_name=category.name if category else f"Category {category_id}",
                record_ids=_ids(bad),
                record_count=len(bad),
                source_types=frozenset(r.source_type for r in bad),
                reason=f"Aggregation requires review: record(s) {ids} have an unknown unit.",
            )
        )
    return results


def aggregate_production(
    records: Iterable[ProductionRecord],
    window: Period,
) -> list[CalculationResult]:
    """Production totals per (scope, dimension); kg and m are never added together."""
    groups: dict[tuple[str | None, str], list[ProductionRecord]] = {}
    unknown: dict[str | None, list[ProductionRecord]] = {}
    for record in records:
        if not record.period.overlaps(window):
            continue
        try:
            dimension = dimension_of(record.unit)
        except UnitError:
            unknown.setdefault(record.scope_key, []).append(record)
            continue
        groups.setdefault((record.scope_key, dimension), []).append(record)

    results: list[CalculationResult] = []
    for key in sorted(groups, key=_sort_key):
        scope_key, dimension = key
        results.append(
            _aggregate_group(
                groups[key],
                window,
                calculation="production_total",
                scope_key=scope_key,
                dimension=dimension,
                target_unit=canonical_unit_for(dimension),
                noun="production",
            )
        )
    for scope_key, bad in sorted(unknown.items(), key=lambda kv: _sort_key((kv[0],))):
        ids = ", ".join(str(i) for i in _ids(bad))
        results.append(
            CalculationResult(
                calculation="production_total",
                status=CalcStatus.UNAVAILABLE,
                window=window,
                scope_key=scope_key,
                dimension="unknown",
                record_ids=_ids(bad),
                record_count=len(bad),
                source_types=frozenset(r.source_type for r in bad),
                reason=f"Aggregation requires review: production record(s) {ids} have an unknown unit.",
            )
        )
    return results


def _safe_dimension(unit: str) -> str | None:
    try:
        return dimension_of(unit)
    except UnitError:
        return None


# --------------------------------------------------------------------------- intensity
def _intensity_unavailable(
    resource: CalculationResult | None,
    production: CalculationResult | None,
    window: Period,
    production_dimension: str,
    reason: str,
    *,
    category_id: int | None = None,
    category_name: str | None = None,
    scope_key: str | None = None,
    resource_dimension: str = "",
) -> IntensityResult:
    return IntensityResult(
        status=CalcStatus.UNAVAILABLE,
        window=window,
        scope_key=resource.scope_key if resource else scope_key,
        category_id=resource.category_id if resource else category_id,
        category_name=resource.category_name if resource else category_name,
        resource_dimension=resource.dimension if resource else resource_dimension,
        production_dimension=production_dimension,
        numerator=resource,
        denominator=production,
        record_ids=resource.record_ids if resource else (),
        production_record_ids=production.record_ids if production else (),
        source_types=(resource.source_types if resource else frozenset())
        | (production.source_types if production else frozenset()),
        reason=reason,
    )


def compute_intensity(
    resource: CalculationResult | None,
    production: CalculationResult | None,
    *,
    window: Period,
    production_dimension: str,
    category_id: int | None = None,
    category_name: str | None = None,
    scope_key: str | None = None,
    resource_dimension: str = "",
) -> IntensityResult:
    """Combine one resource total and one production total into an intensity.

    Every compatibility condition from the calculation specification is checked
    here so the interface can never divide unrelated quantities.
    """
    basis = DIMENSION_LABELS.get(production_dimension, production_dimension).lower()

    def fail(reason: str) -> IntensityResult:
        return _intensity_unavailable(
            resource,
            production,
            window,
            production_dimension,
            reason,
            category_id=category_id,
            category_name=category_name,
            scope_key=scope_key,
            resource_dimension=resource_dimension,
        )

    if resource is None:
        return fail("Intensity unavailable: no resource records exist for this selection.")
    if not resource.is_available:
        return fail(f"Intensity unavailable: resource total is unavailable. {resource.reason or ''}".strip())
    if production is None:
        return fail(
            f"Intensity unavailable: no {basis}-based production records exist for this scope "
            "in the selected period."
        )
    if not production.is_available:
        return fail(f"Intensity unavailable: production total is unavailable. {production.reason or ''}".strip())
    if resource.window != production.window:
        return fail("Intensity unavailable: resource and production reporting periods do not match.")
    if resource.scope_key != production.scope_key:
        return fail("Intensity unavailable: resource and production operational scopes are incompatible.")
    if resource.coverage != production.coverage:
        return fail(
            f"Intensity unavailable: resource records cover {resource.coverage_days} day(s) and "
            f"production records cover {production.coverage_days} day(s) of the period, and the "
            "covered days differ. Complete the missing records or choose a matching period."
        )
    assert resource.value is not None and production.value is not None
    try:
        value = calculate_intensity(resource.value, production.value)
    except DomainError as exc:
        return fail(str(exc))

    warnings = tuple(dict.fromkeys(resource.warnings + production.warnings))
    return IntensityResult(
        status=CalcStatus.VALID_WITH_WARNINGS if warnings else CalcStatus.VALID,
        window=window,
        scope_key=resource.scope_key,
        category_id=resource.category_id,
        category_name=resource.category_name,
        resource_dimension=resource.dimension,
        production_dimension=production_dimension,
        value=value,
        unit=f"{resource.unit}/{production.unit}",
        numerator=resource,
        denominator=production,
        record_ids=resource.record_ids,
        production_record_ids=production.record_ids,
        source_types=resource.source_types | production.source_types,
        warnings=warnings,
    )


def compute_intensities(
    resource_results: Iterable[CalculationResult],
    production_results: Iterable[CalculationResult],
    *,
    window: Period,
    production_dimension: str,
) -> list[IntensityResult]:
    """One intensity per resource total, using production of the chosen basis."""
    production_by_scope = {
        r.scope_key: r for r in production_results if r.dimension == production_dimension
    }
    return [
        compute_intensity(
            resource,
            production_by_scope.get(resource.scope_key),
            window=window,
            production_dimension=production_dimension,
        )
        for resource in resource_results
    ]


def overall_intensity(
    period_results: Sequence[IntensityResult],
    *,
    window: Period,
    template: IntensityResult | None = None,
) -> IntensityResult:
    """Overall intensity = sum of consumption / sum of production.

    Only periods with a valid intensity contribute, and the exclusion of any other
    period is reported as a warning. This is deliberately not an average of
    period-level ratios, which would weight periods incorrectly.
    """
    reference = template or (period_results[0] if period_results else None)
    category_id = reference.category_id if reference else None
    category_name = reference.category_name if reference else None
    scope_key = reference.scope_key if reference else None
    resource_dimension = reference.resource_dimension if reference else ""
    production_dimension = reference.production_dimension if reference else ""

    def fail(reason: str) -> IntensityResult:
        return IntensityResult(
            status=CalcStatus.UNAVAILABLE,
            window=window,
            scope_key=scope_key,
            category_id=category_id,
            category_name=category_name,
            resource_dimension=resource_dimension,
            production_dimension=production_dimension,
            reason=reason,
        )

    valid = [r for r in period_results if r.is_available]
    if not valid:
        return fail("Overall intensity unavailable: no period has a valid intensity.")
    units = {r.unit for r in valid}
    if len(units) != 1:
        return fail("Overall intensity unavailable: periods use different units.")

    consumption = Decimal(0)
    production = Decimal(0)
    for result in valid:
        assert result.numerator and result.denominator
        assert result.numerator.value is not None and result.denominator.value is not None
        consumption = CTX.add(consumption, result.numerator.value)
        production = CTX.add(production, result.denominator.value)
    try:
        value = calculate_intensity(consumption, production)
    except DomainError as exc:
        return fail(str(exc))

    excluded = len(period_results) - len(valid)
    warnings = [
        w for r in valid for w in r.warnings
    ]
    warnings = list(dict.fromkeys(warnings))
    if excluded:
        warnings.append(
            f"{excluded} of {len(period_results)} period(s) had no valid intensity and are not "
            "included in this overall value."
        )
    return IntensityResult(
        status=CalcStatus.VALID_WITH_WARNINGS if warnings else CalcStatus.VALID,
        window=window,
        scope_key=scope_key,
        category_id=category_id,
        category_name=category_name,
        resource_dimension=resource_dimension,
        production_dimension=production_dimension,
        value=value,
        unit=valid[0].unit,
        record_ids=tuple(sorted({i for r in valid for i in r.record_ids})),
        production_record_ids=tuple(sorted({i for r in valid for i in r.production_record_ids})),
        source_types=frozenset().union(*(r.source_types for r in valid)),
        warnings=tuple(warnings),
    )


# ------------------------------------------------------------------------- filtering
def filter_resource_records(
    records: Iterable[ResourceRecord],
    *,
    category_id: int,
    scope_key: str | None,
    dimension: str,
) -> list[ResourceRecord]:
    """Records of one category, scope and physical dimension."""
    return [
        r
        for r in records
        if r.category_id == category_id
        and r.scope_key == scope_key
        and _safe_dimension(r.unit) == dimension
    ]


def filter_production_records(
    records: Iterable[ProductionRecord],
    *,
    scope_key: str | None,
    dimension: str,
) -> list[ProductionRecord]:
    """Production records of one scope and physical dimension."""
    return [r for r in records if r.scope_key == scope_key and _safe_dimension(r.unit) == dimension]


def canonical_production_unit(dimension: str) -> str:
    """Unit used for production totals of a dimension."""
    return CANONICAL_UNITS[dimension]
