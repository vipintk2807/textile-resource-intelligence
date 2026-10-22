"""Validation of resource and production record fields.

Functions return structured :class:`Issue` objects instead of raising so the UI
and the CSV importer can show every problem at once. Nothing is silently
coerced: invalid input is reported, never changed into a valid-looking value.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date, datetime

from .errors import QuantityError, UnitError
from .numbers import parse_decimal
from .types import Issue, Period, Severity, ValidatedFields
from .units import normalize_unit, unit_display, units_for

INTERVAL_RECORD_TYPE = "interval_consumption"
SOURCE_TYPES = ("manual", "import", "demo")

MIN_YEAR = 1900
MAX_YEAR = 2100
MAX_REFERENCE_LENGTH = 100
MAX_NOTES_LENGTH = 1000

_SCOPE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_METER_TYPES = {"meter_reading", "cumulative", "cumulative_reading", "meter"}


def parse_date(value: object, *, label: str = "Date") -> date:
    """Accept ``date`` objects or ISO ``YYYY-MM-DD`` text; reject everything else."""
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError(f"{label} is required.")
        if not _ISO_DATE.match(text):
            raise ValueError(f"{label} must be written as YYYY-MM-DD (for example 2025-01-31).")
        try:
            parsed = date.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"{label} '{text}' is not a real calendar date.") from exc
    elif value is None:
        raise ValueError(f"{label} is required.")
    else:
        raise ValueError(f"{label} must be a valid date.")
    if not MIN_YEAR <= parsed.year <= MAX_YEAR:
        raise ValueError(f"{label} must be between the years {MIN_YEAR} and {MAX_YEAR}.")
    return parsed


def normalize_scope_key(value: object) -> str | None:
    """Return a validated scope key, ``None`` for blank, or raise ValueError.

    Scope keys are identifiers the user defines consistently across resource and
    production records (for example ``dyeing-1``). Records only match when their
    keys are identical; the application never guesses that two keys are related.
    Leading/trailing spaces are removed and letters are lower-cased.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Scope key must be text.")
    text = value.strip().lower()
    if not text:
        return None
    if not _SCOPE_PATTERN.match(text):
        raise ValueError(
            "Scope key may use letters, digits, '-' and '_' (maximum 40 characters, "
            "starting with a letter or digit), for example 'dyeing-1'."
        )
    return text


def _clean_text(value: object, label: str, max_length: int, issues: list[Issue], field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        issues.append(Issue(field, "invalid", f"{label} must be text."))
        return None
    text = value.strip()
    if not text:
        return None
    if len(text) > max_length:
        issues.append(Issue(field, "too_long", f"{label} must be at most {max_length} characters."))
        return None
    if any(ord(ch) < 32 and ch not in "\n\t" for ch in text):
        issues.append(Issue(field, "invalid", f"{label} contains control characters."))
        return None
    return text


def validate_record_fields(
    kind: str,
    *,
    quantity: object,
    unit: object,
    period_start: object,
    period_end: object = None,
    scope_key: object = None,
    reference: object = None,
    notes: object = None,
    record_type: object = INTERVAL_RECORD_TYPE,
    allowed_units: Sequence[str] | None = None,
    category_name: str | None = None,
) -> tuple[ValidatedFields | None, list[Issue]]:
    """Validate one resource (``kind="resource"``) or production record.

    ``allowed_units`` restricts the unit to a category's permitted units. Returns
    ``(fields, issues)``; ``fields`` is ``None`` when any issue is an error.
    """
    if kind not in {"resource", "production"}:
        raise ValueError("kind must be 'resource' or 'production'")
    issues: list[Issue] = []

    # Quantity
    parsed_quantity = None
    try:
        parsed_quantity = parse_decimal(quantity)
    except QuantityError as exc:
        issues.append(Issue("quantity", "invalid_quantity", str(exc)))
    else:
        if parsed_quantity < 0:
            what = "consumption" if kind == "resource" else "production"
            issues.append(
                Issue(
                    "quantity",
                    "negative_quantity",
                    f"Negative {what} quantities are not accepted. Enter zero or a positive "
                    "value (no adjustment workflow is defined).",
                )
            )

    # Unit
    unit_code = None
    try:
        unit_code = normalize_unit(unit)
    except UnitError as exc:
        issues.append(Issue("unit", "unsupported_unit", str(exc)))
    if unit_code is not None:
        if unit_code not in units_for(kind):
            issues.append(
                Issue("unit", "unit_not_valid_for_kind", f"{unit_display(unit_code)} cannot be used for {kind} records.")
            )
        elif allowed_units is not None and unit_code not in allowed_units:
            target = f" for {category_name}" if category_name else ""
            permitted = ", ".join(unit_display(u) for u in allowed_units)
            issues.append(
                Issue(
                    "unit",
                    "unit_not_permitted",
                    f"{unit_display(unit_code)} is not a permitted unit{target}. Permitted: {permitted}.",
                )
            )

    # Period
    start = end = None
    try:
        start = parse_date(period_start, label="Period start")
    except ValueError as exc:
        issues.append(Issue("period_start", "invalid_date", str(exc)))
    blank_end = period_end is None or (isinstance(period_end, str) and not period_end.strip())
    if blank_end:
        end = start
    else:
        try:
            end = parse_date(period_end, label="Period end")
        except ValueError as exc:
            issues.append(Issue("period_end", "invalid_date", str(exc)))
    period = None
    if start is not None and end is not None:
        if end < start:
            issues.append(
                Issue("period_end", "invalid_period", "Period end must not be before the period start.")
            )
        else:
            period = Period(start, end)

    # Scope, reference, notes
    scope = None
    try:
        scope = normalize_scope_key(scope_key)
    except ValueError as exc:
        issues.append(Issue("scope_key", "invalid_scope", str(exc)))
    clean_reference = _clean_text(reference, "Reference", MAX_REFERENCE_LENGTH, issues, "reference")
    clean_notes = _clean_text(notes, "Notes", MAX_NOTES_LENGTH, issues, "notes")

    # Record type (resource only)
    rtype = INTERVAL_RECORD_TYPE
    if kind == "resource":
        raw_type = INTERVAL_RECORD_TYPE if record_type in (None, "") else record_type
        text = str(raw_type).strip().lower()
        if text in _METER_TYPES:
            issues.append(
                Issue(
                    "record_type",
                    "meter_reading_unsupported",
                    "Cumulative meter readings are not supported in this release. Enter the "
                    "consumption for the interval instead.",
                )
            )
        elif text != INTERVAL_RECORD_TYPE:
            issues.append(
                Issue("record_type", "unsupported_record_type", f"Unsupported record type '{raw_type}'.")
            )

    if any(i.is_error for i in issues) or parsed_quantity is None or unit_code is None or period is None:
        return None, issues
    return (
        ValidatedFields(
            quantity=parsed_quantity,
            unit=unit_code,
            period=period,
            scope_key=scope,
            reference=clean_reference,
            notes=clean_notes,
            record_type=rtype,
        ),
        issues,
    )


def warning(field: str, code: str, message: str, row: int | None = None) -> Issue:
    """Convenience constructor for a warning-level issue."""
    return Issue(field, code, message, Severity.WARNING, row)
