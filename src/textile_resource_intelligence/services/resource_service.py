"""Create, read, update and delete resource-consumption records."""

from __future__ import annotations

from ..domain.types import Issue, ResourceRecord
from ..domain.validation import validate_record_fields
from ..exceptions import NotFound, ValidationFailed
from ..schemas import RecordQuery, ResourceDraft, ResourceRecordInput, SaveResult
from .duplicates import duplicate_issues
from .ports import Repository, UnitOfWorkFactory


class ResourceService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow = uow_factory

    # ------------------------------------------------------------------ helpers
    def _prepare(
        self,
        repo: Repository,
        data: ResourceRecordInput,
        existing: ResourceRecord | None,
    ) -> tuple[ResourceDraft, list[Issue]]:
        issues: list[Issue] = []
        category = None
        if data.resource_category_id is not None:
            category = repo.get_category(int(data.resource_category_id))
        if category is None:
            issues.append(Issue("resource_category_id", "required", "Select a resource category."))

        allowed = None
        if category is not None:
            allowed = set(category.allowed_units)
            if existing is not None and existing.category_id == category.id:
                allowed.add(existing.unit)  # editing must not strand a historical unit
            if not category.is_active and (existing is None or existing.category_id != category.id):
                issues.append(
                    Issue(
                        "resource_category_id",
                        "inactive_category",
                        f"The category '{category.name}' is inactive. Reactivate it in Settings or "
                        "choose another category.",
                    )
                )

        fields, field_issues = validate_record_fields(
            "resource",
            quantity=data.quantity,
            unit=data.unit,
            period_start=data.period_start,
            period_end=data.period_end,
            scope_key=data.scope_key,
            reference=data.reference,
            notes=data.notes,
            record_type=data.record_type,
            allowed_units=sorted(allowed) if allowed is not None else None,
            category_name=category.name if category else None,
        )
        issues.extend(field_issues)
        if fields is None or category is None or any(i.is_error for i in issues):
            raise ValidationFailed(issues)

        candidates = repo.list_resource_records(
            RecordQuery(
                date_from=fields.period.start, date_to=fields.period.end, category_id=category.id
            )
        )
        others = [r for r in candidates if existing is None or r.id != existing.id]
        dup_issues, _ = duplicate_issues(fields, others, category_id=category.id)
        issues.extend(dup_issues)
        if any(i.is_error for i in issues):
            raise ValidationFailed(issues)

        source = existing.source_type if existing is not None else "manual"
        assert category.id is not None
        return ResourceDraft(category_id=category.id, fields=fields, source_type=source), issues

    # --------------------------------------------------------------------- API
    def create(self, data: ResourceRecordInput, *, source_type: str = "manual") -> SaveResult:
        """Validate and store a new record. Raises ValidationFailed on any error."""
        with self._uow() as repo:
            draft, issues = self._prepare(repo, data, None)
            draft = ResourceDraft(draft.category_id, draft.fields, source_type)
            record = repo.add_resource_record(draft)
        return SaveResult(record, tuple(i for i in issues if not i.is_error))

    def update(self, record_id: int, data: ResourceRecordInput) -> SaveResult:
        """Validate and apply an edit using the same rules as creation."""
        with self._uow() as repo:
            existing = repo.get_resource_record(record_id)
            if existing is None:
                raise NotFound(f"Resource record #{record_id} no longer exists.")
            draft, issues = self._prepare(repo, data, existing)
            record = repo.update_resource_record(record_id, draft)
            if record is None:
                raise NotFound(f"Resource record #{record_id} no longer exists.")
        return SaveResult(record, tuple(i for i in issues if not i.is_error))

    def delete(self, record_id: int) -> None:
        with self._uow() as repo:
            if not repo.delete_resource_record(record_id):
                raise NotFound(f"Resource record #{record_id} no longer exists.")

    def get(self, record_id: int) -> ResourceRecord:
        with self._uow() as repo:
            record = repo.get_resource_record(record_id)
        if record is None:
            raise NotFound(f"Resource record #{record_id} no longer exists.")
        return record

    def list(self, query: RecordQuery | None = None) -> list[ResourceRecord]:
        with self._uow() as repo:
            return repo.list_resource_records(query or RecordQuery())
