"""CSV export of source records and derived results.

* Source-record exports use the same column names as the importer (plus extra
  context columns, which the importer ignores) so they can be re-imported.
* Derived exports state the reporting period, units, numerator/denominator, status
  and reason. Unavailable values are exported as empty cells, never as zero.
* Text that could be read as a spreadsheet formula (starting with = + - @, tab or
  carriage return) is prefixed with an apostrophe. Numeric columns are untouched.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from decimal import Decimal

import pandas as pd

from ..domain.numbers import CTX, decimal_to_text
from ..domain.types import CalculationResult, ComparisonResult, IntensityResult, Period
from ..domain.units import DIMENSION_LABELS, unit_label
from ..schemas import ExportResult, RecordQuery
from .analysis_service import AnalysisService, ComparisonView
from .ports import UnitOfWorkFactory

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def sanitize_cell(value: object) -> object:
    """Neutralise formula-like text; leave numbers, empty values and safe text alone."""
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def dataframe_to_csv_bytes(frame: pd.DataFrame, numeric_columns: Iterable[str] = ()) -> bytes:
    """Serialise to UTF-8 (with BOM for Excel) after formula-injection protection."""
    numeric = set(numeric_columns)
    safe = frame.copy()
    for column in safe.columns:
        if column not in numeric:
            safe[column] = [sanitize_cell(v) for v in safe[column].tolist()]
    return safe.to_csv(index=False, lineterminator="\r\n").encode("utf-8-sig")


def _num(value: Decimal | None) -> str:
    """Plain-text number without trailing zeros (no rounding); empty when unavailable."""
    return "" if value is None else decimal_to_text(CTX.normalize(value))


def _period_cols(window: Period) -> dict[str, str]:
    return {"report_period_start": window.start.isoformat(), "report_period_end": window.end.isoformat()}


def _ids(ids: Sequence[int]) -> str:
    return ";".join(str(i) for i in ids)


def _origin(source_type: str) -> str:
    return "synthetic demonstration data" if source_type == "demo" else "user-entered or imported"


def _notes(result) -> str:
    parts = list(result.warnings)
    if result.reason:
        parts.insert(0, result.reason)
    return " | ".join(parts)


class ExportService:
    def __init__(self, uow_factory: UnitOfWorkFactory, analysis: AnalysisService) -> None:
        self._uow = uow_factory
        self._analysis = analysis

    def _result(self, name: str, frame: pd.DataFrame, numeric: Iterable[str]) -> ExportResult:
        now = datetime.now(UTC)
        return ExportResult(
            filename=f"{name}_{now:%Y%m%d_%H%M%S}.csv",
            content=dataframe_to_csv_bytes(frame, numeric),
            rows=len(frame),
            columns=tuple(frame.columns),
            generated_at=now,
        )

    # ------------------------------------------------------------ source records
    def resource_records(self, query: RecordQuery | None = None) -> ExportResult:
        query = query or RecordQuery()
        with self._uow() as repo:
            categories = {c.id: c for c in repo.list_categories()}
            records = repo.list_resource_records(query)
        quality = self._analysis.resource_quality()
        rows = []
        for r in records:
            q = quality.get(r.id)
            rows.append({
                "record_id": r.id,
                "resource_category": categories[r.category_id].name if r.category_id in categories else "",
                "period_start": r.period.start.isoformat(),
                "period_end": r.period.end.isoformat(),
                "scope_key": r.scope_key or "",
                "quantity": _num(r.quantity),
                "unit": unit_label(r.unit),
                "reference": r.reference or "",
                "notes": r.notes or "",
                "record_type": r.record_type,
                "source_type": r.source_type,
                "data_origin": _origin(r.source_type),
                "data_quality_status": q.status if q else "",
                "data_quality_notes": " | ".join(q.reasons) if q else "",
            })
        cols = ["record_id", "resource_category", "period_start", "period_end", "scope_key", "quantity",
                "unit", "reference", "notes", "record_type", "source_type", "data_origin",
                "data_quality_status", "data_quality_notes"]
        return self._result("resource_records", pd.DataFrame(rows, columns=cols), ["record_id", "quantity"])

    def production_records(self, query: RecordQuery | None = None) -> ExportResult:
        query = query or RecordQuery()
        with self._uow() as repo:
            records = repo.list_production_records(query)
        quality = self._analysis.production_quality()
        rows = []
        for r in records:
            q = quality.get(r.id)
            rows.append({
                "record_id": r.id,
                "period_start": r.period.start.isoformat(),
                "period_end": r.period.end.isoformat(),
                "scope_key": r.scope_key or "",
                "quantity": _num(r.quantity),
                "unit": unit_label(r.unit),
                "reference": r.reference or "",
                "notes": r.notes or "",
                "source_type": r.source_type,
                "data_origin": _origin(r.source_type),
                "data_quality_status": q.status if q else "",
                "data_quality_notes": " | ".join(q.reasons) if q else "",
            })
        cols = ["record_id", "period_start", "period_end", "scope_key", "quantity", "unit", "reference",
                "notes", "source_type", "data_origin", "data_quality_status", "data_quality_notes"]
        return self._result("production_records", pd.DataFrame(rows, columns=cols), ["record_id", "quantity"])

    # ---------------------------------------------------------- derived results
    def resource_summaries(self, window: Period) -> ExportResult:
        overview = self._analysis.overview(window)
        rows = [self._total_row(window, t) for t in overview.resource_totals]
        cols = list(rows[0].keys()) if rows else list(self._total_row_columns())
        return self._result("resource_totals", pd.DataFrame(rows, columns=cols), ["total_quantity", "record_count", "days_covered", "days_in_period"])

    @staticmethod
    def _total_row_columns() -> list[str]:
        return ["report_period_start", "report_period_end", "resource_category", "scope_key", "dimension",
                "total_quantity", "unit", "record_count", "source_record_ids", "days_covered",
                "days_in_period", "status", "reason_or_warnings", "includes_synthetic_demo_records"]

    def _total_row(self, window: Period, t: CalculationResult) -> dict:
        return {
            **_period_cols(window),
            "resource_category": t.category_name or "",
            "scope_key": t.scope_key or "",
            "dimension": DIMENSION_LABELS.get(t.dimension, t.dimension),
            "total_quantity": _num(t.value),
            "unit": unit_label(t.unit),
            "record_count": t.record_count,
            "source_record_ids": _ids(t.record_ids),
            "days_covered": t.coverage_days if t.is_available else "",
            "days_in_period": window.days,
            "status": t.status.value,
            "reason_or_warnings": _notes(t),
            "includes_synthetic_demo_records": "demo" in t.source_types,
        }

    def intensities(self, window: Period, production_dimension: str | None = None) -> ExportResult:
        overview = self._analysis.overview(window, production_dimension)
        rows = [self._intensity_row(window, i) for i in overview.intensities]
        cols = ["report_period_start", "report_period_end", "resource_category", "scope_key",
                "production_basis", "resource_total", "resource_unit", "production_total",
                "production_unit", "intensity", "intensity_unit", "status", "reason_or_warnings",
                "resource_record_ids", "production_record_ids", "includes_synthetic_demo_records"]
        return self._result("resource_intensity", pd.DataFrame(rows, columns=cols),
                            ["resource_total", "production_total", "intensity"])

    def _intensity_row(self, window: Period, i: IntensityResult) -> dict:
        n, d = i.numerator, i.denominator
        return {
            **_period_cols(window),
            "resource_category": i.category_name or "",
            "scope_key": i.scope_key or "",
            "production_basis": DIMENSION_LABELS.get(i.production_dimension, i.production_dimension),
            "resource_total": _num(n.value if n and n.is_available else None),
            "resource_unit": unit_label(n.unit) if n and n.is_available else "",
            "production_total": _num(d.value if d and d.is_available else None),
            "production_unit": unit_label(d.unit) if d and d.is_available else "",
            "intensity": _num(i.value),
            "intensity_unit": unit_label(i.unit),
            "status": i.status.value,
            "reason_or_warnings": _notes(i),
            "resource_record_ids": _ids(i.record_ids),
            "production_record_ids": _ids(i.production_record_ids),
            "includes_synthetic_demo_records": "demo" in i.source_types,
        }

    def comparison(self, view: ComparisonView) -> ExportResult:
        rows = []
        for name, cmp, cur, base in (
            ("resource_total", view.total_comparison, view.current_total, view.baseline_total),
            ("production_total", view.production_comparison, view.current_production, view.baseline_production),
            ("resource_intensity", view.intensity_comparison, view.current_intensity, view.baseline_intensity),
        ):
            rows.append(self._comparison_row(view, name, cmp, cur, base))
        cols = list(rows[0].keys())
        return self._result("baseline_comparison", pd.DataFrame(rows, columns=cols),
                            ["current_value", "baseline_value", "absolute_difference", "percent_change_vs_baseline"])

    def _comparison_row(self, view, name, cmp: ComparisonResult, cur, base) -> dict:
        sources = (cur.source_types if cur else frozenset()) | (base.source_types if base else frozenset())
        return {
            "resource_category": view.category.name,
            "scope_key": view.scope_key or "",
            "metric": name,
            "current_period_start": view.current_window.start.isoformat(),
            "current_period_end": view.current_window.end.isoformat(),
            "baseline_period_start": view.baseline_window.start.isoformat(),
            "baseline_period_end": view.baseline_window.end.isoformat(),
            "current_value": _num(cmp.current_value),
            "baseline_value": _num(cmp.baseline_value),
            "unit": unit_label(cmp.unit),
            "absolute_difference": _num(cmp.absolute_difference),
            "percent_change_vs_baseline": _num(cmp.percent_change),
            "status": cmp.status.value,
            "reason_or_warnings": " | ".join(([cmp.reason] if cmp.reason else [])
                                             + ([cmp.percent_reason] if cmp.percent_reason else [])
                                             + list(cmp.warnings)),
            "baseline_reference": cmp.baseline_reference,
            "includes_synthetic_demo_records": "demo" in sources,
        }

    def data_quality(self, window: Period) -> ExportResult:
        overview = self._analysis.overview(window)
        rows = [{**_period_cols(window), "kind": w.kind, "message": w.message, "related_page": w.page}
                for w in overview.warnings]
        cols = ["report_period_start", "report_period_end", "kind", "message", "related_page"]
        return self._result("data_quality_warnings", pd.DataFrame(rows, columns=cols), [])
