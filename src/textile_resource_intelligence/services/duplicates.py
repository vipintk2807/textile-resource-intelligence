"""Duplicate-detection policy shared by manual entry and CSV import.

* Reliable duplicate: the new record has a reference and another record has the
  same reference, scope and period (and category, for resource records).
* Potential duplicate: same scope, period, quantity and unit and at least one of the
  two records has no reference to tell them apart. Never removed automatically;
  reported for review. Equal quantities alone never make a record a duplicate.
"""

from __future__ import annotations

from collections.abc import Iterable

from ..domain.types import Issue, ProductionRecord, ResourceRecord, Severity, ValidatedFields


def _same_event(fields: ValidatedFields, other, *, category_id: int | None) -> bool:
    if category_id is not None and getattr(other, "category_id", None) != category_id:
        return False
    return other.scope_key == fields.scope_key and other.period == fields.period


def reliable_duplicates(
    fields: ValidatedFields,
    existing: Iterable[ResourceRecord | ProductionRecord],
    *,
    category_id: int | None = None,
) -> list[ResourceRecord | ProductionRecord]:
    if fields.reference is None:
        return []
    return [
        r
        for r in existing
        if r.reference == fields.reference and _same_event(fields, r, category_id=category_id)
    ]


def potential_duplicates(
    fields: ValidatedFields,
    existing: Iterable[ResourceRecord | ProductionRecord],
    *,
    category_id: int | None = None,
) -> list[ResourceRecord | ProductionRecord]:
    return [
        r
        for r in existing
        if _same_event(fields, r, category_id=category_id)
        and r.quantity == fields.quantity
        and r.unit == fields.unit
        and (r.reference is None or fields.reference is None)
    ]


def duplicate_issues(
    fields: ValidatedFields,
    existing: Iterable[ResourceRecord | ProductionRecord],
    *,
    category_id: int | None = None,
    row: int | None = None,
) -> tuple[list[Issue], bool]:
    """Issues for a candidate record and whether it is a reliable duplicate."""
    existing = list(existing)
    reliable = reliable_duplicates(fields, existing, category_id=category_id)
    if reliable:
        ids = ", ".join(f"#{r.id}" for r in reliable if r.id is not None) or "an existing record"
        return (
            [
                Issue(
                    "reference",
                    "duplicate_reference",
                    f"A record with the same reference, scope and period already exists ({ids}). "
                    "Change the reference or edit the existing record.",
                    Severity.ERROR,
                    row,
                )
            ],
            True,
        )
    potential = potential_duplicates(fields, existing, category_id=category_id)
    if potential:
        ids = ", ".join(f"#{r.id}" for r in potential if r.id is not None) or "an existing record"
        return (
            [
                Issue(
                    "quantity",
                    "possible_duplicate",
                    f"This looks like a possible duplicate of {ids} (same scope, period, quantity and "
                    "unit, no reference to tell them apart). It was kept; review it if unintended.",
                    Severity.WARNING,
                    row,
                )
            ],
            False,
        )
    return [], False
