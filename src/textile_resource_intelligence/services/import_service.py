"""CSV import: parse -> map columns -> validate -> duplicate policy -> atomic commit.

Import policy (documented in the README):

* All-or-nothing: if any row has an error nothing is written.
* Rows whose reference/scope/period (and category) match an existing record or an
  earlier row of the same file are skipped as reliable duplicates and reported.
* Rows without a reference that resemble an existing record are imported but flagged
  as possible duplicates; nothing is ever removed automatically.
* The same code path serves the preview (``dry_run=True``) and the commit, so the
  commit is validated against the database as it is at commit time.
"""

from __future__ import annotations

import csv
import io
import re

from ..domain.types import Category, Issue, Severity
from ..domain.validation import validate_record_fields
from ..exceptions import ImportFileError
from ..schemas import (
    CsvTable,
    ImportLimits,
    ImportReport,
    ProductionDraft,
    RecordQuery,
    ResourceDraft,
)
from .duplicates import potential_duplicates, reliable_duplicates
from .ports import UnitOfWorkFactory

RESOURCE_FIELDS = (
    ("resource_category", True),
    ("quantity", True),
    ("unit", True),
    ("period_start", True),
    ("period_end", False),
    ("scope_key", False),
    ("reference", False),
    ("notes", False),
    ("record_type", False),
)
PRODUCTION_FIELDS = (
    ("quantity", True),
    ("unit", True),
    ("period_start", True),
    ("period_end", False),
    ("scope_key", False),
    ("reference", False),
    ("notes", False),
)
_SYNONYMS = {
    "resource_category": {"resource_category", "category", "resource", "resource_name"},
    "quantity": {"quantity", "qty", "amount", "consumption"},
    "unit": {"unit", "units", "uom"},
    "period_start": {"period_start", "start", "start_date", "date", "period_from"},
    "period_end": {"period_end", "end", "end_date", "period_to"},
    "scope_key": {"scope_key", "scope"},
    "reference": {"reference", "ref", "record_id", "batch"},
    "notes": {"notes", "note", "comment", "comments"},
    "record_type": {"record_type", "type"},
}


def fields_for(kind: str) -> tuple[tuple[str, bool], ...]:
    if kind == "resource":
        return RESOURCE_FIELDS
    if kind == "production":
        return PRODUCTION_FIELDS
    raise ValueError("kind must be 'resource' or 'production'")


def _norm(name: str) -> str:
    return re.sub(r"[\s\-]+", "_", name.strip().lower())


def template_csv(kind: str) -> bytes:
    """A header-only CSV template (UTF-8 with BOM so Excel opens it correctly)."""
    header = ",".join(name for name, _ in fields_for(kind))
    return ("\ufeff" + header + "\r\n").encode("utf-8")


def suggest_mapping(columns: tuple[str, ...] | list[str], kind: str) -> dict[str, str | None]:
    """Preselect a source column for each application field (users can override)."""
    normalized = {_norm(c): c for c in columns}
    mapping: dict[str, str | None] = {}
    for field, _required in fields_for(kind):
        mapping[field] = None
        for synonym in (field, *sorted(_SYNONYMS[field])):
            if synonym in normalized:
                mapping[field] = normalized[synonym]
                break
    return mapping


def read_csv_bytes(content: bytes, limits: ImportLimits | None = None) -> CsvTable:
    """Parse CSV bytes into a table of text cells or raise ImportFileError."""
    limits = limits or ImportLimits()
    if not content:
        raise ImportFileError("The file is empty. Choose a CSV file that contains a header row and data.")
    if len(content) > limits.max_bytes:
        raise ImportFileError(
            f"The file is larger than the {limits.max_bytes // (1024 * 1024)} MB import limit. "
            "Split it into smaller files."
        )
    if b"\x00" in content:
        raise ImportFileError("The file looks like a binary file, not a CSV text file.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ImportFileError(
            "The file is not valid UTF-8 text. In Excel use 'Save As > CSV UTF-8 (Comma delimited)'."
        ) from exc
    if not text.strip():
        raise ImportFileError("The file contains no data.")
    try:
        raw_rows = [r for r in csv.reader(io.StringIO(text, newline=""), strict=True)]
    except csv.Error as exc:
        detail = " ".join(str(exc).split())[:200]
        raise ImportFileError(f"The file is not a well-formed CSV file ({detail}).") from exc
    # Fully blank lines (and whitespace-only lines) carry no data.
    raw_rows = [r for r in raw_rows if r and not (len(r) == 1 and not r[0].strip())]
    if not raw_rows:
        raise ImportFileError("The file contains no data.")

    columns = tuple(c.strip() for c in raw_rows[0])
    if not any(columns):
        raise ImportFileError("The first row must be a header row with column names.")
    if any(not c for c in columns):
        raise ImportFileError("The header row contains an empty column name.")
    seen: set[str] = set()
    for column in columns:
        if column in seen:
            raise ImportFileError(f"The header contains the column '{column}' more than once.")
        seen.add(column)
    data = raw_rows[1:]
    if not data:
        raise ImportFileError("The file has a header but no data rows.")
    if len(data) > limits.max_rows:
        raise ImportFileError(
            f"The file has {len(data):,} data rows; the limit is {limits.max_rows:,}. Split the file."
        )
    for number, row in enumerate(data, start=1):
        if len(row) != len(columns):
            raise ImportFileError(
                f"Row {number} has {len(row)} values but the header has {len(columns)} columns. "
                "Check for missing or extra commas (values containing commas must be in quotes)."
            )
    return CsvTable(columns=columns, rows=tuple(dict(zip(columns, row, strict=True)) for row in data))


class ImportService:
    def __init__(self, uow_factory: UnitOfWorkFactory, limits: ImportLimits | None = None) -> None:
        self._uow = uow_factory
        self._limits = limits or ImportLimits()

    def inspect(self, content: bytes) -> CsvTable:
        """Parse a file so the interface can show its columns for mapping."""
        return read_csv_bytes(content, self._limits)

    def run(
        self,
        content: bytes,
        kind: str,
        mapping: dict[str, str | None],
        *,
        dry_run: bool,
        source_type: str = "import",
    ) -> ImportReport:
        """Validate (``dry_run=True``) or validate and commit a CSV import."""
        fields = fields_for(kind)
        table = read_csv_bytes(content, self._limits)
        issues: list[Issue] = []

        for field, required in fields:
            column = mapping.get(field)
            if column is not None and column not in table.columns:
                issues.append(Issue(field, "unknown_column", f"Mapped column '{column}' is not in the file."))
                mapping = {**mapping, field: None}
            if required and mapping.get(field) is None:
                issues.append(
                    Issue(field, "missing_column", f"The required field '{field}' is not mapped to a file column.")
                )
        mapped_columns = {c for c in mapping.values() if c}
        ignored = tuple(c for c in table.columns if c not in mapped_columns)
        if any(i.is_error for i in issues):
            return ImportReport(
                kind=kind,
                dry_run=dry_run,
                total_rows=len(table.rows),
                ignored_columns=ignored,
                issues=tuple(issues),
            )

        with self._uow() as repo:
            categories: dict[str, Category] = {}
            existing: list = []
            if kind == "resource":
                categories = {c.name.casefold(): c for c in repo.list_categories()}
                existing = repo.list_resource_records(RecordQuery())
            else:
                existing = repo.list_production_records(RecordQuery())

            drafts: list = []
            seen: list = []  # records already accepted from this file
            empty_rows = rejected = skipped = with_warnings = 0

            for number, row in enumerate(table.rows, start=1):
                values = {
                    field: (row.get(mapping[field], "") if mapping.get(field) else "")
                    for field, _ in fields
                }
                if not any(v.strip() for v in values.values()):
                    empty_rows += 1
                    continue

                row_issues: list[Issue] = []
                category: Category | None = None
                if kind == "resource":
                    name = " ".join(values["resource_category"].split())
                    category = categories.get(name.casefold()) if name else None
                    if not name:
                        row_issues.append(Issue("resource_category", "required", "Resource category is required.", row=number))
                    elif category is None:
                        row_issues.append(
                            Issue("resource_category", "unknown_category",
                                  f"Unknown resource category '{name}'. Create it in Settings first.", row=number)
                        )
                    elif not category.is_active:
                        row_issues.append(
                            Issue("resource_category", "inactive_category",
                                  f"The category '{category.name}' is inactive.", row=number)
                        )

                validated, field_issues = validate_record_fields(
                    kind,
                    quantity=values["quantity"],
                    unit=values["unit"],
                    period_start=values["period_start"],
                    period_end=values["period_end"],
                    scope_key=values["scope_key"],
                    reference=values["reference"],
                    notes=values["notes"],
                    record_type=values.get("record_type", ""),
                    allowed_units=list(category.allowed_units) if category else None,
                    category_name=category.name if category else None,
                )
                row_issues.extend(Issue(i.field, i.code, i.message, i.severity, number) for i in field_issues)

                if validated is None or any(i.is_error for i in row_issues):
                    rejected += 1
                    issues.extend(row_issues)
                    continue

                category_id = category.id if category else None
                pool = [*existing, *seen]
                if reliable_duplicates(validated, pool, category_id=category_id):
                    skipped += 1
                    issues.append(
                        Issue("reference", "duplicate_skipped",
                              f"Skipped: a record with reference '{validated.reference}' for the same "
                              "scope and period already exists.", Severity.WARNING, number)
                    )
                    continue
                if potential_duplicates(validated, pool, category_id=category_id):
                    with_warnings += 1
                    row_issues.append(
                        Issue("quantity", "possible_duplicate",
                              "Possible duplicate of an existing or earlier record (same scope, period, "
                              "quantity and unit, no reference). It will be imported; review it afterwards.",
                              Severity.WARNING, number)
                    )
                issues.extend(row_issues)
                if kind == "resource":
                    assert category_id is not None
                    drafts.append(ResourceDraft(category_id, validated, source_type))
                    seen.append(_as_record(kind, validated, category_id))
                else:
                    drafts.append(ProductionDraft(validated, source_type))
                    seen.append(_as_record(kind, validated, None))

            report = ImportReport(
                kind=kind,
                dry_run=dry_run,
                total_rows=len(table.rows),
                empty_rows=empty_rows,
                valid_rows=len(drafts),
                rows_with_warnings=with_warnings,
                rejected_rows=rejected,
                skipped_duplicates=skipped,
                ignored_columns=ignored,
                issues=tuple(issues),
            )
            if dry_run or report.errors or not drafts:
                return report

            for draft in drafts:
                if kind == "resource":
                    repo.add_resource_record(draft)
                else:
                    repo.add_production_record(draft)
            inserted = len(drafts)

        return ImportReport(
            kind=kind,
            dry_run=False,
            total_rows=report.total_rows,
            empty_rows=report.empty_rows,
            valid_rows=report.valid_rows,
            rows_with_warnings=report.rows_with_warnings,
            rejected_rows=report.rejected_rows,
            skipped_duplicates=report.skipped_duplicates,
            inserted=inserted,
            committed=True,
            ignored_columns=report.ignored_columns,
            issues=report.issues,
        )


def _as_record(kind: str, fields, category_id: int | None):
    from ..domain.types import ProductionRecord, ResourceRecord

    if kind == "resource":
        return ResourceRecord(None, category_id or 0, fields.quantity, fields.unit, fields.period,
                              fields.scope_key, fields.reference, fields.notes)
    return ProductionRecord(None, fields.quantity, fields.unit, fields.period,
                            fields.scope_key, fields.reference, fields.notes)
