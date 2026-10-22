"""Plain data types shared by the domain, service and UI layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from enum import Enum


class Severity(str, Enum):
    """Whether an issue blocks saving (error) or only needs attention (warning)."""

    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class Issue:
    """A structured validation message that the UI can attach to a field or row."""

    field: str
    code: str
    message: str
    severity: Severity = Severity.ERROR
    row: int | None = None

    @property
    def is_error(self) -> bool:
        return self.severity is Severity.ERROR


@dataclass(frozen=True, order=True)
class Period:
    """An inclusive date interval. A single date has ``start == end``."""

    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError("Period end must not be before its start.")

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def is_single_date(self) -> bool:
        return self.start == self.end

    def contains(self, other: Period) -> bool:
        return self.start <= other.start and other.end <= self.end

    def overlaps(self, other: Period) -> bool:
        return self.start <= other.end and other.start <= self.end

    def label(self) -> str:
        if self.is_single_date:
            return self.start.isoformat()
        return f"{self.start.isoformat()} to {self.end.isoformat()}"


@dataclass(frozen=True)
class Category:
    """A configured resource category."""

    id: int | None
    name: str
    resource_type: str
    default_unit: str
    allowed_units: tuple[str, ...]
    is_active: bool = True


@dataclass(frozen=True)
class ValidatedFields:
    """Fields of a resource or production record that passed validation."""

    quantity: Decimal
    unit: str
    period: Period
    scope_key: str | None
    reference: str | None
    notes: str | None
    record_type: str = "interval_consumption"


@dataclass(frozen=True)
class ResourceRecord:
    """A stored resource-consumption record (original quantity and unit preserved)."""

    id: int | None
    category_id: int
    quantity: Decimal
    unit: str
    period: Period
    scope_key: str | None = None
    reference: str | None = None
    notes: str | None = None
    source_type: str = "manual"
    record_type: str = "interval_consumption"


@dataclass(frozen=True)
class ProductionRecord:
    """A stored production record (original quantity and unit preserved)."""

    id: int | None
    quantity: Decimal
    unit: str
    period: Period
    scope_key: str | None = None
    reference: str | None = None
    notes: str | None = None
    source_type: str = "manual"


class CalcStatus(str, Enum):
    """Outcome of a calculation. A valid zero is VALID; missing data is UNAVAILABLE."""

    VALID = "valid"
    VALID_WITH_WARNINGS = "valid_with_warnings"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class CalculationResult:
    """A traceable aggregate (resource total or production total)."""

    calculation: str  # "resource_total" or "production_total"
    status: CalcStatus
    window: Period
    scope_key: str | None
    dimension: str
    category_id: int | None = None
    category_name: str | None = None
    value: Decimal | None = None
    unit: str | None = None
    record_ids: tuple[int, ...] = ()
    record_count: int = 0
    source_types: frozenset[str] = frozenset()
    coverage: tuple[Period, ...] = ()
    coverage_days: int = 0
    warnings: tuple[str, ...] = ()
    reason: str | None = None

    @property
    def is_available(self) -> bool:
        return self.status is not CalcStatus.UNAVAILABLE and self.value is not None

    @property
    def coverage_complete(self) -> bool:
        """True when the included records cover every day of the window."""
        return self.coverage_days == self.window.days


@dataclass(frozen=True)
class IntensityResult:
    """Resource consumption per unit of production for one period and scope."""

    status: CalcStatus
    window: Period
    scope_key: str | None
    category_id: int | None
    category_name: str | None
    resource_dimension: str
    production_dimension: str
    value: Decimal | None = None
    unit: str | None = None
    numerator: CalculationResult | None = None
    denominator: CalculationResult | None = None
    record_ids: tuple[int, ...] = ()
    production_record_ids: tuple[int, ...] = ()
    source_types: frozenset[str] = frozenset()
    warnings: tuple[str, ...] = ()
    reason: str | None = None
    calculation: str = "intensity"

    @property
    def is_available(self) -> bool:
        return self.status is not CalcStatus.UNAVAILABLE and self.value is not None


@dataclass(frozen=True)
class ComparisonResult:
    """Current value versus a baseline, with the reasons for anything unavailable."""

    status: CalcStatus
    calculation: str
    unit: str | None
    current_value: Decimal | None
    baseline_value: Decimal | None
    absolute_difference: Decimal | None
    percent_change: Decimal | None
    reason: str | None = None
    percent_reason: str | None = None
    warnings: tuple[str, ...] = ()
    current_reference: str = ""
    baseline_reference: str = ""

    @property
    def is_available(self) -> bool:
        return self.status is not CalcStatus.UNAVAILABLE


@dataclass(frozen=True)
class QualityAssessment:
    """Data-quality status of one stored record."""

    status: str  # "valid", "review" or "invalid"
    reasons: tuple[str, ...] = field(default_factory=tuple)


def day_after(value: date) -> date:
    """The calendar day following ``value``."""
    return value + timedelta(days=1)
