"""Typed data contracts passed between the UI, services and repositories.

These are plain dataclasses: raw ``*Input`` objects carry unvalidated user input,
``*Draft`` objects carry validated values that are ready to persist.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal

from .domain.types import (
    Issue,
    ProductionRecord,
    ResourceRecord,
    ValidatedFields,
)
from .domain.validation import INTERVAL_RECORD_TYPE

ScopeMode = Literal["any", "overall", "key"]


# ------------------------------------------------------------------ raw user input
@dataclass(frozen=True)
class ResourceRecordInput:
    resource_category_id: int | None
    quantity: object
    unit: object
    period_start: object
    period_end: object = None
    scope_key: object = None
    reference: object = None
    notes: object = None
    record_type: object = INTERVAL_RECORD_TYPE


@dataclass(frozen=True)
class ProductionRecordInput:
    quantity: object
    unit: object
    period_start: object
    period_end: object = None
    scope_key: object = None
    reference: object = None
    notes: object = None


@dataclass(frozen=True)
class CategoryInput:
    name: object
    resource_type: object
    default_unit: object
    allowed_units: object


# ------------------------------------------------------------------ validated drafts
@dataclass(frozen=True)
class CategoryDraft:
    name: str
    resource_type: str
    default_unit: str
    allowed_units: tuple[str, ...]
    is_active: bool = True


@dataclass(frozen=True)
class ResourceDraft:
    category_id: int
    fields: ValidatedFields
    source_type: str = "manual"


@dataclass(frozen=True)
class ProductionDraft:
    fields: ValidatedFields
    source_type: str = "manual"


# -------------------------------------------------------------------------- queries
@dataclass(frozen=True)
class RecordQuery:
    """Filters for listing records. Dates select records that overlap the range."""

    date_from: object = None  # datetime.date | None
    date_to: object = None  # datetime.date | None
    category_id: int | None = None
    scope_mode: ScopeMode = "any"
    scope_key: str | None = None
    source_type: str | None = None
    text: str | None = None


@dataclass(frozen=True)
class RecordCounts:
    resource: int = 0
    production: int = 0
    demo_resource: int = 0
    demo_production: int = 0

    @property
    def total(self) -> int:
        return self.resource + self.production

    @property
    def demo_total(self) -> int:
        return self.demo_resource + self.demo_production


@dataclass(frozen=True)
class SaveResult:
    """Outcome of a successful save, with any non-blocking warnings."""

    record: ResourceRecord | ProductionRecord
    warnings: tuple[Issue, ...] = ()


# ---------------------------------------------------------------------------- import
@dataclass(frozen=True)
class ImportLimits:
    max_bytes: int = 5 * 1024 * 1024
    max_rows: int = 50_000


@dataclass(frozen=True)
class CsvTable:
    """A parsed CSV file; every cell is kept as the original text."""

    columns: tuple[str, ...]
    rows: tuple[dict[str, str], ...]


@dataclass(frozen=True)
class ImportReport:
    """Result of validating (dry run) or committing a CSV import.

    Row numbers count data rows after the header: the first data row is row 1.
    """

    kind: str
    dry_run: bool
    total_rows: int = 0
    empty_rows: int = 0
    valid_rows: int = 0
    rows_with_warnings: int = 0
    rejected_rows: int = 0
    skipped_duplicates: int = 0
    inserted: int = 0
    committed: bool = False
    ignored_columns: tuple[str, ...] = ()
    issues: tuple[Issue, ...] = field(default_factory=tuple)

    @property
    def errors(self) -> tuple[Issue, ...]:
        return tuple(i for i in self.issues if i.is_error)

    @property
    def warnings(self) -> tuple[Issue, ...]:
        return tuple(i for i in self.issues if not i.is_error)

    @property
    def can_commit(self) -> bool:
        return not self.errors and (self.valid_rows > 0)


# -------------------------------------------------------------------- preferences
@dataclass(frozen=True)
class Preferences:
    default_period_mode: str = "month"
    intensity_threshold_pct: Decimal | None = None
    display_decimals: int = 2


# ----------------------------------------------------------------------------- export
@dataclass(frozen=True)
class ExportResult:
    filename: str
    content: bytes
    rows: int
    columns: tuple[str, ...]
    generated_at: datetime
