"""Plotly figures. Missing or unavailable periods are gaps, never zeros."""

from __future__ import annotations

import plotly.graph_objects as go

from ..domain.types import CalcStatus, ComparisonResult
from ..domain.units import unit_label
from ..services.analysis_service import TrendData
from .theme import INFO, NAVY, NEUTRAL, TEAL, WARNING

_LAYOUT = dict(
    template="plotly_white",
    margin=dict(l=10, r=10, t=40, b=10),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    font=dict(family="Inter, Segoe UI, Arial, sans-serif", color="#344054"),
)


def _label(period) -> str:
    return period.start.strftime("%Y-%m") if period.days > 1 else period.start.isoformat()


def _float(value):
    return None if value is None else float(value)


def total_trend_figure(trend: TrendData, title: str) -> go.Figure:
    x, y, hover = [], [], []
    for b in trend.buckets:
        x.append(_label(b.period))
        total = b.total
        available = total is not None and total.is_available
        y.append(_float(total.value) if available else None)
        if total is None:
            hover.append("No records")
        elif not available:
            hover.append(f"Unavailable: {total.reason}")
        else:
            note = "; ".join(total.warnings)
            hover.append(f"{total.value:,.2f} {unit_label(total.unit)}" + (f"<br>{note}" if note else ""))
    fig = go.Figure(go.Bar(x=x, y=y, marker_color=TEAL, hovertext=hover, hoverinfo="text",
                           name=f"Total consumption ({unit_label(trend.resource_unit)})"))
    fig.update_layout(title=title, yaxis_title=unit_label(trend.resource_unit), **_LAYOUT)
    fig.update_yaxes(rangemode="tozero")
    return fig


def intensity_trend_figure(trend: TrendData, title: str) -> go.Figure:
    x, y, symbols, hover = [], [], [], []
    unit = ""
    for b in trend.buckets:
        i = b.intensity
        x.append(_label(b.period))
        y.append(_float(i.value) if i.is_available else None)
        symbols.append("diamond" if i.status is CalcStatus.VALID_WITH_WARNINGS else "circle")
        if i.is_available:
            unit = unit_label(i.unit)
            note = "; ".join(i.warnings)
            hover.append(f"{i.value:,.3f} {unit_label(i.unit)}" + (f"<br>{note}" if note else ""))
        else:
            hover.append(f"Unavailable: {i.reason}")
    fig = go.Figure(go.Scatter(x=x, y=y, mode="lines+markers", connectgaps=False, line=dict(color=NAVY),
                               marker=dict(symbol=symbols, size=9), hovertext=hover, hoverinfo="text",
                               name="Intensity"))
    fig.update_layout(title=title, yaxis_title=unit or "intensity", **_LAYOUT)
    fig.update_yaxes(rangemode="tozero")
    return fig


def production_trend_figure(trend: TrendData, title: str) -> go.Figure:
    x = [_label(b.period) for b in trend.buckets]
    y = [_float(b.production.value) if b.production is not None and b.production.is_available else None
         for b in trend.buckets]
    fig = go.Figure(go.Bar(x=x, y=y, marker_color=NEUTRAL, name=f"Production ({unit_label(trend.production_unit)})"))
    fig.update_layout(title=title, yaxis_title=unit_label(trend.production_unit), **_LAYOUT)
    fig.update_yaxes(rangemode="tozero")
    return fig


def comparison_figure(comparison: ComparisonResult, title: str) -> go.Figure | None:
    """Two bars (baseline, current) on a zero-based axis; ``None`` when unavailable."""
    if comparison.current_value is None or comparison.baseline_value is None:
        return None
    fig = go.Figure(go.Bar(
        x=["Baseline", "Current"],
        y=[float(comparison.baseline_value), float(comparison.current_value)],
        marker_color=[INFO, WARNING if comparison.current_value > comparison.baseline_value else TEAL],
        text=[f"{float(comparison.baseline_value):,.3f}", f"{float(comparison.current_value):,.3f}"],
        textposition="outside",
    ))
    fig.update_layout(title=title, yaxis_title=unit_label(comparison.unit), showlegend=False, **_LAYOUT)
    fig.update_yaxes(rangemode="tozero")
    return fig
