"""Build display tables (pandas DataFrames) from domain results. Pure and testable."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

import pandas as pd

from ..domain.types import (
    CalculationResult,
    Category,
    IntensityResult,
    ProductionRecord,
    QualityAssessment,
    ResourceRecord,
)
from ..domain.units import unit_label
from .formatting import (
    UNAVAILABLE,
    dimension_label,
    format_decimal,
    format_period,
    format_raw_quantity,
    format_scope,
    quality_text,
    source_label,
    status_text,
)


def resource_records_frame(
    records: Iterable[ResourceRecord],
    categories: Mapping[int, Category],
    quality: Mapping[int, QualityAssessment],
) -> pd.DataFrame:
    rows = []
    for r in records:
        q = quality.get(r.id)
        rows.append({
            "ID": r.id,
            "Period": format_period(r.period),
            "Resource category": categories[r.category_id].name if r.category_id in categories else "?",
            "Quantity (as recorded)": format_raw_quantity(r.quantity),
            "Unit": unit_label(r.unit),
            "Scope": format_scope(r.scope_key),
            "Reference": r.reference or "",
            "Source": source_label(r.source_type),
            "Data quality": quality_text(q.status) if q else "",
            "Quality notes": " ".join(q.reasons) if q else "",
        })
    return pd.DataFrame(rows, columns=["ID", "Period", "Resource category", "Quantity (as recorded)", "Unit",
                                       "Scope", "Reference", "Source", "Data quality", "Quality notes"])


def production_records_frame(
    records: Iterable[ProductionRecord],
    quality: Mapping[int, QualityAssessment],
) -> pd.DataFrame:
    rows = []
    for r in records:
        q = quality.get(r.id)
        rows.append({
            "ID": r.id,
            "Period": format_period(r.period),
            "Production quantity (as recorded)": format_raw_quantity(r.quantity),
            "Unit": unit_label(r.unit),
            "Scope": format_scope(r.scope_key),
            "Reference": r.reference or "",
            "Source": source_label(r.source_type),
            "Data quality": quality_text(q.status) if q else "",
            "Quality notes": " ".join(q.reasons) if q else "",
        })
    return pd.DataFrame(rows, columns=["ID", "Period", "Production quantity (as recorded)", "Unit", "Scope",
                                       "Reference", "Source", "Data quality", "Quality notes"])


def _coverage_text(result: CalculationResult) -> str:
    if not result.is_available:
        return "—"
    return f"{result.coverage_days} of {result.window.days} days"


def totals_frame(results: Sequence[CalculationResult], places: int = 2) -> pd.DataFrame:
    rows = []
    for t in results:
        rows.append({
            "Resource": t.category_name or "",
            "Scope": format_scope(t.scope_key),
            "Measurement": dimension_label(t.dimension),
            "Total consumption": format_decimal(t.value, places) if t.is_available else UNAVAILABLE,
            "Unit": unit_label(t.unit) if t.is_available else "",
            "Records": t.record_count,
            "Coverage": _coverage_text(t),
            "Status": status_text(t.status),
            "Details": " ".join(([t.reason] if t.reason else []) + list(t.warnings)),
        })
    return pd.DataFrame(rows, columns=["Resource", "Scope", "Measurement", "Total consumption", "Unit", "Records",
                                       "Coverage", "Status", "Details"])


def production_totals_frame(results: Sequence[CalculationResult], places: int = 2) -> pd.DataFrame:
    rows = []
    for t in results:
        rows.append({
            "Scope": format_scope(t.scope_key),
            "Production basis": dimension_label(t.dimension),
            "Recorded production": format_decimal(t.value, places) if t.is_available else UNAVAILABLE,
            "Unit": unit_label(t.unit) if t.is_available else "",
            "Records": t.record_count,
            "Coverage": _coverage_text(t),
            "Status": status_text(t.status),
            "Details": " ".join(([t.reason] if t.reason else []) + list(t.warnings)),
        })
    return pd.DataFrame(rows, columns=["Scope", "Production basis", "Recorded production", "Unit", "Records",
                                       "Coverage", "Status", "Details"])


def intensities_frame(results: Sequence[IntensityResult], places: int = 2) -> pd.DataFrame:
    rows = []
    for i in results:
        n, d = i.numerator, i.denominator
        rows.append({
            "Resource": i.category_name or "",
            "Scope": format_scope(i.scope_key),
            "Resource total": (f"{format_decimal(n.value, places)} {unit_label(n.unit)}"
                               if n and n.is_available else UNAVAILABLE),
            "Production": (f"{format_decimal(d.value, places)} {unit_label(d.unit)}"
                           if d and d.is_available else UNAVAILABLE),
            "Intensity": f"{format_decimal(i.value, places)} {unit_label(i.unit)}" if i.is_available else UNAVAILABLE,
            "Status": status_text(i.status),
            "Details": " ".join(([i.reason] if i.reason else []) + list(i.warnings)),
        })
    return pd.DataFrame(rows, columns=["Resource", "Scope", "Resource total", "Production", "Intensity", "Status",
                                       "Details"])
