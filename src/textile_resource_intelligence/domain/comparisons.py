"""Baseline comparison: absolute difference and percentage change.

A comparison is available only for valid, non-negative values in identical units
and compatible scope. A zero baseline keeps the absolute difference but marks the
percentage unavailable. A change is a calculated observation, never proof of cause.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from .errors import QuantityError
from .numbers import CTX, parse_decimal
from .types import CalcStatus, ComparisonResult, Period
from .units import unit_label


class _Comparable(Protocol):
    calculation: str
    status: CalcStatus
    value: Decimal | None
    unit: str | None
    scope_key: str | None
    category_id: int | None
    window: Period
    warnings: tuple[str, ...]
    reason: str | None


def _clean(value: object, label: str) -> tuple[Decimal | None, str | None]:
    if value is None:
        return None, f"{label} is missing."
    try:
        number = parse_decimal(value, label=label, enforce_limits=False)
    except QuantityError:
        return None, f"{label} is invalid."
    if number < 0:
        return None, f"{label} is negative and cannot be compared."
    return number, None


def compare_values(
    current: object,
    baseline: object,
    *,
    current_unit: str | None = None,
    baseline_unit: str | None = None,
    calculation: str = "value",
) -> ComparisonResult:
    """Compare two plain values. See module docstring for the availability rules."""

    def unavailable(reason: str, cur: Decimal | None = None, base: Decimal | None = None) -> ComparisonResult:
        return ComparisonResult(
            status=CalcStatus.UNAVAILABLE,
            calculation=calculation,
            unit=current_unit or baseline_unit,
            current_value=cur,
            baseline_value=base,
            absolute_difference=None,
            percent_change=None,
            reason=reason,
        )

    if current_unit is not None and baseline_unit is not None and current_unit != baseline_unit:
        return unavailable(
            f"Comparison unavailable: units are incompatible ({unit_label(current_unit)} vs "
            f"{unit_label(baseline_unit)})."
        )
    cur, cur_reason = _clean(current, "Current value")
    base, base_reason = _clean(baseline, "Baseline value")
    if cur is None:
        return unavailable(f"Comparison unavailable: {cur_reason}", None, base)
    if base is None:
        return unavailable(f"Comparison unavailable: {base_reason}", cur, None)

    difference = CTX.subtract(cur, base)
    if base == 0:
        return ComparisonResult(
            status=CalcStatus.VALID_WITH_WARNINGS,
            calculation=calculation,
            unit=current_unit or baseline_unit,
            current_value=cur,
            baseline_value=base,
            absolute_difference=difference,
            percent_change=None,
            percent_reason="Percentage change unavailable: baseline value is zero.",
            warnings=("Percentage change is unavailable because the baseline value is zero.",),
        )
    percent = CTX.multiply(CTX.divide(difference, base), Decimal(100))
    return ComparisonResult(
        status=CalcStatus.VALID,
        calculation=calculation,
        unit=current_unit or baseline_unit,
        current_value=cur,
        baseline_value=base,
        absolute_difference=difference,
        percent_change=percent,
    )


def describe_reference(result: _Comparable | None, label: str) -> str:
    """Traceable text identifying the period and scope behind a compared value."""
    if result is None:
        return f"{label}: none"
    scope = result.scope_key or "overall (no scope)"
    return f"{label}: {result.window.label()}, scope {scope}"


def compare_results(
    current: _Comparable | None,
    baseline: _Comparable | None,
) -> ComparisonResult:
    """Compare two calculation or intensity results after checking compatibility."""
    current_ref = describe_reference(current, "Current period")
    baseline_ref = describe_reference(baseline, "Baseline period")
    calculation = (current or baseline).calculation if (current or baseline) else "value"

    def unavailable(reason: str) -> ComparisonResult:
        return ComparisonResult(
            status=CalcStatus.UNAVAILABLE,
            calculation=calculation,
            unit=(current.unit if current else None),
            current_value=current.value if current and current.is_available else None,  # type: ignore[attr-defined]
            baseline_value=baseline.value if baseline and baseline.is_available else None,  # type: ignore[attr-defined]
            absolute_difference=None,
            percent_change=None,
            reason=reason,
            current_reference=current_ref,
            baseline_reference=baseline_ref,
        )

    if baseline is None:
        return unavailable("Comparison unavailable: no baseline period is available.")
    if current is None:
        return unavailable("Comparison unavailable: no current value is available.")
    if current.status is CalcStatus.UNAVAILABLE or current.value is None:
        return unavailable(f"Comparison unavailable: the current value is unavailable. {current.reason or ''}".strip())
    if baseline.status is CalcStatus.UNAVAILABLE or baseline.value is None:
        return unavailable(f"Comparison unavailable: the baseline value is unavailable. {baseline.reason or ''}".strip())
    if current.calculation != baseline.calculation:
        return unavailable("Comparison unavailable: the values measure different things.")
    if current.category_id != baseline.category_id:
        return unavailable("Comparison unavailable: the values belong to different resource categories.")
    if current.scope_key != baseline.scope_key:
        return unavailable("Comparison unavailable: operational scopes are incompatible.")
    if current.unit != baseline.unit:
        return unavailable(
            f"Comparison unavailable: units are incompatible ({unit_label(current.unit)} vs "
            f"{unit_label(baseline.unit)})."
        )

    base_result = compare_values(
        current.value,
        baseline.value,
        current_unit=current.unit,
        baseline_unit=baseline.unit,
        calculation=calculation,
    )
    warnings = list(base_result.warnings)
    if current.window == baseline.window:
        warnings.append("The current and baseline periods are identical.")
    elif current.window.days != baseline.window.days and calculation.endswith("_total"):
        warnings.append(
            f"The periods have different lengths ({current.window.days} vs {baseline.window.days} "
            "days), so totals are not directly comparable."
        )
    warnings.extend(f"Current period: {w}" for w in current.warnings)
    warnings.extend(f"Baseline period: {w}" for w in baseline.warnings)
    status = base_result.status
    if warnings and status is CalcStatus.VALID:
        status = CalcStatus.VALID_WITH_WARNINGS
    return ComparisonResult(
        status=status,
        calculation=calculation,
        unit=current.unit,
        current_value=base_result.current_value,
        baseline_value=base_result.baseline_value,
        absolute_difference=base_result.absolute_difference,
        percent_change=base_result.percent_change,
        reason=base_result.reason,
        percent_reason=base_result.percent_reason,
        warnings=tuple(dict.fromkeys(warnings)),
        current_reference=current_ref,
        baseline_reference=baseline_ref,
    )
