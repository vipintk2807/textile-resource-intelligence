"""Create, read, update and delete production records."""

from __future__ import annotations

from ..domain.types import Issue, ProductionRecord
from ..domain.validation import validate_record_fields
from ..exceptions import NotFound, ValidationFailed
from ..schemas import ProductionDraft, ProductionRecordInput, RecordQuery, SaveResult
from .duplicates import duplicate_issues
from .ports import Repository, UnitOfWorkFactory


class ProductionService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow = uow_factory

    def _prepare(
        self,
        repo: Repository,
        data: ProductionRecordInput,
        existing: ProductionRecord | None,
    ) -> tuple[ProductionDraft, list[Issue]]:
        fields, issues = validate_record_fields(
            "production",
            quantity=data.quantity,
            unit=data.unit,
            period_start=data.period_start,
            period_end=data.period_end,
            scope_key=data.scope_key,
            reference=data.reference,
            notes=data.notes,
        )
        if fields is None:
            raise ValidationFailed(issues)
        candidates = repo.list_production_records(
            RecordQuery(date_from=fields.period.start, date_to=fields.period.end)
        )
        others = [r for r in candidates if existing is None or r.id != existing.id]
        dup_issues, _ = duplicate_issues(fields, others)
        issues = list(issues) + dup_issues
        if any(i.is_error for i in issues):
            raise ValidationFailed(issues)
        source = existing.source_type if existing is not None else "manual"
        return ProductionDraft(fields=fields, source_type=source), issues

    def create(self, data: ProductionRecordInput, *, source_type: str = "manual") -> SaveResult:
        """Validate and store a new production record (zero is allowed, negatives are not)."""
        with self._uow() as repo:
            draft, issues = self._prepare(repo, data, None)
            record = repo.add_production_record(ProductionDraft(draft.fields, source_type))
        return SaveResult(record, tuple(i for i in issues if not i.is_error))

    def update(self, record_id: int, data: ProductionRecordInput) -> SaveResult:
        with self._uow() as repo:
            existing = repo.get_production_record(record_id)
            if existing is None:
                raise NotFound(f"Production record #{record_id} no longer exists.")
            draft, issues = self._prepare(repo, data, existing)
            record = repo.update_production_record(record_id, draft)
            if record is None:
                raise NotFound(f"Production record #{record_id} no longer exists.")
        return SaveResult(record, tuple(i for i in issues if not i.is_error))

    def delete(self, record_id: int) -> None:
        with self._uow() as repo:
            if not repo.delete_production_record(record_id):
                raise NotFound(f"Production record #{record_id} no longer exists.")

    def get(self, record_id: int) -> ProductionRecord:
        with self._uow() as repo:
            record = repo.get_production_record(record_id)
        if record is None:
            raise NotFound(f"Production record #{record_id} no longer exists.")
        return record

    def list(self, query: RecordQuery | None = None) -> list[ProductionRecord]:
        with self._uow() as repo:
            return repo.list_production_records(query or RecordQuery())
