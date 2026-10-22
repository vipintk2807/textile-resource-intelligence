"""Display formatting. Pure functions: they never change calculation values."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from ..domain.types import CalcStatus, Period
from ..domain.units import DIMENSION_LABELS, unit_label

UNAVAILABLE = "Unavailable"
EM_DASH = "—"

STATUS_LABELS = {
    CalcStatus.VALID: "Valid",
    CalcStatus.VALID_WITH_WARNINGS: "Valid, with warnings",
    CalcStatus.UNAVAILABLE: "Unavailable",
}
# Text accompanies every status so colour or symbol is never the only indicator.
STATUS_SYMBOLS = {
    CalcStatus.VALID: "✔",
    CalcStatus.VALID_WITH_WARNINGS: "⚠",
    CalcStatus.UNAVAILABLE: "✖",
}
QUALITY_LABELS = {"valid": "Valid", "review": "Needs review", "invalid": "Requires correction"}


def format_decimal(value: Decimal | None, places: int = 2) -> str:
    """Rounded for display only, with thousands separators; ``Unavailable`` if missing."""
    if value is None:
        return UNAVAILABLE
    quantum = Decimal(1).scaleb(-places)
    rounded = value.quantize(quantum, rounding=ROUND_HALF_UP)
    return format(rounded, f",.{places}f")


def format_raw_quantity(value: Decimal | None, max_places: int = 6) -> str:
    """Stored quantity with separators and no padding zeros (up to ``max_places``)."""
    if value is None:
        return EM_DASH
    text = format_decimal(value, max_places)
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def format_quantity(value: Decimal | None, unit: str | None, places: int = 2) -> str:
    """Value and unit kept together, e.g. ``1,200.00 kWh``."""
    if value is None:
        return UNAVAILABLE
    return f"{format_decimal(value, places)} {unit_label(unit)}".strip()


def format_percent(value: Decimal | None, places: int = 1) -> str:
    """Signed percentage versus baseline, or ``Unavailable``."""
    if value is None:
        return UNAVAILABLE
    rounded = value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    sign = "+" if rounded > 0 else ""
    return f"{sign}{rounded:.{places}f}% versus baseline"


def format_signed(value: Decimal | None, unit: str | None, places: int = 2) -> str:
    if value is None:
        return UNAVAILABLE
    rounded = value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    sign = "+" if rounded > 0 else ""
    return f"{sign}{format(rounded, f',.{places}f')} {unit_label(unit)}".strip()


def format_period(period: Period) -> str:
    return period.label()


def format_scope(scope_key: str | None) -> str:
    return scope_key if scope_key else "Overall (no scope)"


def status_text(status: CalcStatus) -> str:
    return f"{STATUS_SYMBOLS[status]} {STATUS_LABELS[status]}"


def quality_text(status: str) -> str:
    symbol = {"valid": "✔", "review": "⚠", "invalid": "✖"}.get(status, "")
    return f"{symbol} {QUALITY_LABELS.get(status, status)}".strip()


def dimension_label(dimension: str) -> str:
    return DIMENSION_LABELS.get(dimension, dimension)


def source_label(source_type: str) -> str:
    return {"manual": "Manual entry", "import": "CSV import", "demo": "Synthetic demo"}.get(source_type, source_type)


def comparison_direction(percent: Decimal | None) -> str:
    """Neutral wording; never 'improvement' or 'deterioration'."""
    if percent is None:
        return "not available"
    if percent == 0:
        return "unchanged"
    return "higher" if percent > 0 else "lower"
