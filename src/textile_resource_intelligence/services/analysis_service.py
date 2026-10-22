"""Analysis: totals, intensities, trends, baseline comparisons and data-quality views.

Everything is recomputed from stored records on every call, so no derived value
can become stale after an edit, import or deletion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from ..domain.calculations import (
    aggregate_production,
    aggregate_resources,
    compute_intensities,
    compute_intensity,
    filter_production_records,
    filter_resource_records,
    make_buckets,
    overall_intensity,
)
from ..domain.comparisons import compare_results
from ..domain.quality import assess_production_records, assess_resource_records, summarize
from ..domain.types import (
    CalcStatus,
    CalculationResult,
    Category,
    ComparisonResult,
    IntensityResult,
    Period,
    ProductionRecord,
    QualityAssessment,
    ResourceRecord,
)
from ..domain.units import DIMENSION_LABELS, canonical_unit_for, dimension_of
from ..schemas import RecordCounts, RecordQuery
from .ports import UnitOfWorkFactory


@dataclass(frozen=True)
class DataQualityWarning:
    kind: str
    message: str
    page: str  # "resource_records", "production_records" or "analysis"


@dataclass(frozen=True)
class OverviewData:
    window: Period
    production_dimension: str | None
    available_production_dimensions: tuple[str, ...]
    resource_totals: tuple[CalculationResult, ...]
    production_totals: tuple[CalculationResult, ...]
    intensities: tuple[IntensityResult, ...]
    warnings: tuple[DataQualityWarning, ...]
    counts: RecordCounts
    quality_counts: dict[str, int]

    @property
    def has_any_data(self) -> bool:
        return self.counts.total > 0

    @property
    def has_data_in_window(self) -> bool:
        return bool(self.resource_totals or self.production_totals)


@dataclass(frozen=True)
class TrendBucket:
    period: Period
    total: CalculationResult | None
    production: CalculationResult | None
    intensity: IntensityResult


@dataclass(frozen=True)
class TrendData:
    buckets: tuple[TrendBucket, ...]
    overall: IntensityResult
    resource_unit: str
    production_unit: str


@dataclass(frozen=True)
class ComparisonView:
    category: Category
    scope_key: str | None
    resource_dimension: str
    production_dimension: str
    current_window: Period
    baseline_window: Period
    current_total: CalculationResult | None
    baseline_total: CalculationResult | None
    current_production: CalculationResult | None
    baseline_production: CalculationResult | None
    current_intensity: IntensityResult
    baseline_intensity: IntensityResult
    total_comparison: ComparisonResult
    production_comparison: ComparisonResult
    intensity_comparison: ComparisonResult
    prompts: tuple[str, ...] = field(default_factory=tuple)


def _pick(results: list[CalculationResult], *, category_id: int | None, scope_key, dimension: str):
    for result in results:
        if (
            result.scope_key == scope_key
            and result.dimension == dimension
            and (category_id is None or result.category_id == category_id)
        ):
            return result
    return None


class AnalysisService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow = uow_factory

    # ---------------------------------------------------------------- loading
    def _load(self) -> tuple[dict[int, Category], list[ResourceRecord], list[ProductionRecord], RecordCounts]:
        with self._uow() as repo:
            categories = {c.id: c for c in repo.list_categories() if c.id is not None}
            resources = repo.list_resource_records(RecordQuery())
            production = repo.list_production_records(RecordQuery())
            counts = repo.count_records()
        return categories, resources, production, counts

    def record_counts(self) -> RecordCounts:
        """Counts of stored records, including synthetic demonstration records."""
        with self._uow() as repo:
            return repo.count_records()

    def latest_record_date(self):
        """Most recent period end across all records (used to pick a sensible default period)."""
        _, resources, production, _ = self._load()
        ends = [r.period.end for r in resources] + [p.period.end for p in production]
        return max(ends) if ends else None

    # --------------------------------------------------------------- overview
    def overview(self, window: Period, production_dimension: str | None = None) -> OverviewData:
        categories, resources, production, counts = self._load()
        resource_totals = aggregate_resources(resources, window, categories)
        production_totals = aggregate_production(production, window)
        dims = tuple(sorted({p.dimension for p in production_totals if p.dimension in DIMENSION_LABELS}))
        basis = production_dimension if production_dimension in dims else _default_basis(dims)
        intensities: list[IntensityResult] = []
        if basis is not None:
            intensities = compute_intensities(
                resource_totals, production_totals, window=window, production_dimension=basis
            )

        assessments = assess_resource_records(resources, production)
        production_assessments = assess_production_records(production)
        quality_counts = summarize({**{("r", k): v for k, v in assessments.items()},
                                    **{("p", k): v for k, v in production_assessments.items()}})
        warnings = self._warnings(window, resources, production, resource_totals, intensities,
                                  assessments, production_assessments, categories)
        return OverviewData(
            window=window,
            production_dimension=basis,
            available_production_dimensions=dims,
            resource_totals=tuple(resource_totals),
            production_totals=tuple(production_totals),
            intensities=tuple(intensities),
            warnings=tuple(warnings),
            counts=counts,
            quality_counts=quality_counts,
        )

    def _warnings(self, window, resources, production, totals, intensities,
                  assessments, production_assessments, categories) -> list[DataQualityWarning]:
        out: list[DataQualityWarning] = []
        for total in totals:
            where = f"{total.category_name}" + (f" (scope {total.scope_key})" if total.scope_key else "")
            if total.status is CalcStatus.UNAVAILABLE:
                out.append(DataQualityWarning("total_unavailable", f"{where}: total unavailable. {total.reason}", "resource_records"))
            else:
                for message in total.warnings:
                    out.append(DataQualityWarning("total_incomplete", f"{where}: {message}", "resource_records"))
        for intensity in intensities:
            if intensity.status is CalcStatus.UNAVAILABLE and intensity.numerator and intensity.numerator.is_available:
                where = f"{intensity.category_name}" + (f" (scope {intensity.scope_key})" if intensity.scope_key else "")
                out.append(DataQualityWarning("intensity_unavailable", f"{where}: {intensity.reason}", "analysis"))
        in_window = {r.id for r in resources if r.period.overlaps(window)}
        no_prod = sum(1 for rid in in_window if any("No positive production" in x for x in assessments[rid].reasons))
        if no_prod:
            out.append(DataQualityWarning("missing_production", f"{no_prod} resource record(s) in this period have no positive production record covering their period.", "production_records"))
        dupes = sum(1 for rid in in_window if any("Possible duplicate" in x for x in assessments[rid].reasons))
        if dupes:
            out.append(DataQualityWarning("possible_duplicates", f"{dupes} resource record(s) in this period look like possible duplicates.", "resource_records"))
        zero = sum(1 for p in production if p.period.overlaps(window) and p.quantity == 0)
        if zero:
            out.append(DataQualityWarning("zero_production", f"{zero} production record(s) in this period record zero production; they cannot be used as intensity denominators.", "production_records"))
        bad = sum(1 for a in assessments.values() if a.status == "invalid") + sum(
            1 for a in production_assessments.values() if a.status == "invalid")
        if bad:
            out.append(DataQualityWarning("invalid_units", f"{bad} record(s) have an unknown unit and need correction.", "resource_records"))
        return out

    # ------------------------------------------------------------------ trend
    def trend(
        self,
        category_id: int,
        scope_key: str | None,
        window: Period,
        *,
        resource_dimension: str,
        production_dimension: str,
        granularity: str = "month",
    ) -> TrendData:
        categories, resources, production, _ = self._load()
        category = categories[category_id]
        res = filter_resource_records(resources, category_id=category_id, scope_key=scope_key, dimension=resource_dimension)
        prod = filter_production_records(production, scope_key=scope_key, dimension=production_dimension)
        buckets: list[TrendBucket] = []
        for period in make_buckets(window, granularity):
            total = _pick(aggregate_resources(res, period, categories), category_id=category_id, scope_key=scope_key, dimension=resource_dimension)
            prod_total = _pick(aggregate_production(prod, period), category_id=None, scope_key=scope_key, dimension=production_dimension)
            intensity = compute_intensity(
                total, prod_total, window=period, production_dimension=production_dimension,
                category_id=category_id, category_name=category.name, scope_key=scope_key,
                resource_dimension=resource_dimension,
            )
            buckets.append(TrendBucket(period, total, prod_total, intensity))
        overall = overall_intensity([b.intensity for b in buckets], window=window,
                                    template=buckets[0].intensity if buckets else None)
        target = category.default_unit if _same_dim(category.default_unit, resource_dimension) else canonical_unit_for(resource_dimension)
        return TrendData(tuple(buckets), overall, target, canonical_unit_for(production_dimension))

    # ------------------------------------------------------------- comparison
    def period_results(
        self,
        category_id: int,
        scope_key: str | None,
        window: Period,
        *,
        resource_dimension: str,
        production_dimension: str,
    ) -> tuple[CalculationResult | None, CalculationResult | None, IntensityResult]:
        """Resource total, production total and intensity for one category, scope and period."""
        categories, resources, production, _ = self._load()
        return self._build(categories, resources, production, category_id, scope_key, window,
                           resource_dimension, production_dimension)

    @staticmethod
    def _build(categories, resources, production, category_id, scope_key, window,
               resource_dimension, production_dimension):
        category = categories[category_id]
        res = filter_resource_records(resources, category_id=category_id, scope_key=scope_key,
                                      dimension=resource_dimension)
        prod = filter_production_records(production, scope_key=scope_key, dimension=production_dimension)
        total = _pick(aggregate_resources(res, window, categories), category_id=category_id,
                      scope_key=scope_key, dimension=resource_dimension)
        ptotal = _pick(aggregate_production(prod, window), category_id=None, scope_key=scope_key,
                       dimension=production_dimension)
        intensity = compute_intensity(
            total, ptotal, window=window, production_dimension=production_dimension,
            category_id=category_id, category_name=category.name, scope_key=scope_key,
            resource_dimension=resource_dimension,
        )
        return total, ptotal, intensity

    def compare(
        self,
        category_id: int,
        scope_key: str | None,
        current_window: Period,
        baseline_window: Period,
        *,
        resource_dimension: str,
        production_dimension: str,
        threshold_pct: Decimal | None = None,
    ) -> ComparisonView:
        """Compare a period with an explicitly chosen baseline period."""
        categories, resources, production, _ = self._load()
        category = categories[category_id]
        args = (categories, resources, production, category_id, scope_key)
        dims = (resource_dimension, production_dimension)
        cur_total, cur_prod, cur_int = self._build(*args, current_window, *dims)
        base_total, base_prod, base_int = self._build(*args, baseline_window, *dims)
        total_cmp = compare_results(cur_total, base_total)
        prod_cmp = compare_results(cur_prod, base_prod)
        int_cmp = compare_results(cur_int, base_int)
        return ComparisonView(
            category=category, scope_key=scope_key, resource_dimension=resource_dimension,
            production_dimension=production_dimension, current_window=current_window,
            baseline_window=baseline_window, current_total=cur_total, baseline_total=base_total,
            current_production=cur_prod, baseline_production=base_prod,
            current_intensity=cur_int, baseline_intensity=base_int,
            total_comparison=total_cmp, production_comparison=prod_cmp, intensity_comparison=int_cmp,
            prompts=tuple(investigation_prompts(category.name, total_cmp, prod_cmp, int_cmp, threshold_pct)),
        )

    # ---------------------------------------------------------------- helpers
    def scopes_for_category(self, category_id: int) -> list[str | None]:
        """Scope keys that occur in this category's records (``None`` = overall)."""
        with self._uow() as repo:
            records = repo.list_resource_records(RecordQuery(category_id=category_id))
        keys = {r.scope_key for r in records}
        return sorted(keys, key=lambda k: (k is not None, k or ""))

    def resource_dimensions(self, category_id: int, scope_key: str | None) -> list[str]:
        with self._uow() as repo:
            records = repo.list_resource_records(RecordQuery(category_id=category_id))
        dims = {dimension_of(r.unit) for r in records if r.scope_key == scope_key}
        return sorted(dims)

    def production_dimensions(self, scope_key: str | None) -> list[str]:
        with self._uow() as repo:
            records = repo.list_production_records(RecordQuery())
        return sorted({dimension_of(r.unit) for r in records if r.scope_key == scope_key})

    def resource_quality(self) -> dict[int, QualityAssessment]:
        _, resources, production, _ = self._load()
        return assess_resource_records(resources, production)

    def production_quality(self) -> dict[int, QualityAssessment]:
        _, _, production, _ = self._load()
        return assess_production_records(production)


def _default_basis(dimensions: tuple[str, ...]) -> str | None:
    """Default production basis for display: mass, then length, then count.

    This only chooses what is shown first. The basis is always labelled and the user can
    switch it; different bases are never combined or treated as equivalent.
    """
    for preferred in ("mass", "length", "count"):
        if preferred in dimensions:
            return preferred
    return dimensions[0] if dimensions else None


def _same_dim(unit: str, dimension: str) -> bool:
    try:
        return dimension_of(unit) == dimension
    except ValueError:
        return False


def investigation_prompts(
    category_name: str,
    totals: ComparisonResult,
    production: ComparisonResult,
    intensity: ComparisonResult,
    threshold_pct: Decimal | None,
) -> list[str]:
    """Neutral prompts to review records. They are not diagnoses and name no cause."""
    prompts: list[str] = []
    if (
        threshold_pct is not None
        and intensity.percent_change is not None
        and intensity.percent_change > threshold_pct
    ):
        prompts.append(
            f"{category_name} intensity is {intensity.percent_change:.1f}% above the selected baseline, "
            f"above your configured review threshold of {threshold_pct}%. Review the underlying "
            "records and operating conditions; this does not identify a cause."
        )
    if (
        totals.percent_change is not None
        and production.percent_change is not None
        and totals.percent_change > 0
        and production.percent_change <= 0
    ):
        prompts.append(
            f"{category_name} total consumption is higher than the baseline while compatible "
            "production did not increase. Review the records for both periods."
        )
    if not intensity.is_available:
        prompts.append(
            "A reliable intensity comparison is not possible with the current records: "
            f"{intensity.reason}"
        )
    return prompts
