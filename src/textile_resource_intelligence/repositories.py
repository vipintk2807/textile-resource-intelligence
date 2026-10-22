"""SQLAlchemy implementation of the Repository port (one instance per transaction)."""

from __future__ import annotations

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from .domain.types import Category, Period, ProductionRecord, ResourceRecord
from .models import CategoryRow, PreferenceRow, ProductionRecordRow, ResourceRecordRow
from .schemas import CategoryDraft, ProductionDraft, RecordCounts, RecordQuery, ResourceDraft


def _category(row: CategoryRow) -> Category:
    return Category(
        id=row.id,
        name=row.name,
        resource_type=row.resource_type,
        default_unit=row.default_unit,
        allowed_units=tuple(u for u in row.allowed_units.split(",") if u),
        is_active=row.is_active,
    )


def _period(row) -> Period:
    return Period(row.period_start, row.period_end or row.period_start)


def _stored_end(period: Period):
    """A single date is stored as NULL ``period_end``."""
    return None if period.is_single_date else period.end


def _resource(row: ResourceRecordRow) -> ResourceRecord:
    return ResourceRecord(
        id=row.id,
        category_id=row.resource_category_id,
        quantity=row.quantity,
        unit=row.unit,
        period=_period(row),
        scope_key=row.scope_key,
        reference=row.reference,
        notes=row.notes,
        source_type=row.source_type,
        record_type=row.record_type,
    )


def _production(row: ProductionRecordRow) -> ProductionRecord:
    return ProductionRecord(
        id=row.id,
        quantity=row.quantity,
        unit=row.unit,
        period=_period(row),
        scope_key=row.scope_key,
        reference=row.reference,
        notes=row.notes,
        source_type=row.source_type,
    )


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _filtered(stmt, model, query: RecordQuery, *, has_category: bool):
    if query.date_from is not None:
        stmt = stmt.where(func.coalesce(model.period_end, model.period_start) >= query.date_from)
    if query.date_to is not None:
        stmt = stmt.where(model.period_start <= query.date_to)
    if has_category and query.category_id is not None:
        stmt = stmt.where(model.resource_category_id == query.category_id)
    if query.scope_mode == "overall":
        stmt = stmt.where(model.scope_key.is_(None))
    elif query.scope_mode == "key":
        stmt = stmt.where(model.scope_key == query.scope_key)
    if query.source_type:
        stmt = stmt.where(model.source_type == query.source_type)
    if query.text:
        like = f"%{_escape_like(query.text.strip())}%"
        stmt = stmt.where(
            or_(
                model.reference.ilike(like, escape="\\"),
                model.notes.ilike(like, escape="\\"),
                model.scope_key.ilike(like, escape="\\"),
            )
        )
    return stmt.order_by(model.period_start, model.id)


class SqlRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ---------------------------------------------------------------- categories
    def list_categories(self) -> list[Category]:
        rows = self.session.scalars(select(CategoryRow).order_by(CategoryRow.id)).all()
        return [_category(r) for r in rows]

    def get_category(self, category_id: int) -> Category | None:
        row = self.session.get(CategoryRow, category_id)
        return _category(row) if row else None

    def find_category_by_name(self, name: str) -> Category | None:
        row = self.session.scalars(
            select(CategoryRow).where(func.lower(CategoryRow.name) == name.casefold())
        ).first()
        return _category(row) if row else None

    def add_category(self, draft: CategoryDraft) -> Category:
        row = CategoryRow(
            name=draft.name,
            resource_type=draft.resource_type,
            default_unit=draft.default_unit,
            allowed_units=",".join(draft.allowed_units),
            is_active=draft.is_active,
        )
        self.session.add(row)
        self.session.flush()
        return _category(row)

    def update_category(self, category_id: int, draft: CategoryDraft) -> Category | None:
        row = self.session.get(CategoryRow, category_id)
        if row is None:
            return None
        row.name = draft.name
        row.resource_type = draft.resource_type
        row.default_unit = draft.default_unit
        row.allowed_units = ",".join(draft.allowed_units)
        row.is_active = draft.is_active
        self.session.flush()
        return _category(row)

    def count_resource_records_in_category(self, category_id: int) -> int:
        return self.session.scalar(
            select(func.count()).select_from(ResourceRecordRow).where(
                ResourceRecordRow.resource_category_id == category_id
            )
        ) or 0

    # ----------------------------------------------------------- resource records
    def add_resource_record(self, draft: ResourceDraft) -> ResourceRecord:
        f = draft.fields
        row = ResourceRecordRow(
            resource_category_id=draft.category_id,
            record_type=f.record_type,
            quantity=f.quantity,
            unit=f.unit,
            period_start=f.period.start,
            period_end=_stored_end(f.period),
            scope_key=f.scope_key,
            reference=f.reference,
            notes=f.notes,
            source_type=draft.source_type,
        )
        self.session.add(row)
        self.session.flush()
        return _resource(row)

    def update_resource_record(self, record_id: int, draft: ResourceDraft) -> ResourceRecord | None:
        row = self.session.get(ResourceRecordRow, record_id)
        if row is None:
            return None
        f = draft.fields
        row.resource_category_id = draft.category_id
        row.quantity = f.quantity
        row.unit = f.unit
        row.period_start = f.period.start
        row.period_end = _stored_end(f.period)
        row.scope_key = f.scope_key
        row.reference = f.reference
        row.notes = f.notes
        self.session.flush()
        return _resource(row)

    def delete_resource_record(self, record_id: int) -> bool:
        row = self.session.get(ResourceRecordRow, record_id)
        if row is None:
            return False
        self.session.delete(row)
        self.session.flush()
        return True

    def get_resource_record(self, record_id: int) -> ResourceRecord | None:
        row = self.session.get(ResourceRecordRow, record_id)
        return _resource(row) if row else None

    def list_resource_records(self, query: RecordQuery) -> list[ResourceRecord]:
        stmt = _filtered(select(ResourceRecordRow), ResourceRecordRow, query, has_category=True)
        return [_resource(r) for r in self.session.scalars(stmt).all()]

    # ---------------------------------------------------------- production records
    def add_production_record(self, draft: ProductionDraft) -> ProductionRecord:
        f = draft.fields
        row = ProductionRecordRow(
            quantity=f.quantity,
            unit=f.unit,
            period_start=f.period.start,
            period_end=_stored_end(f.period),
            scope_key=f.scope_key,
            reference=f.reference,
            notes=f.notes,
            source_type=draft.source_type,
        )
        self.session.add(row)
        self.session.flush()
        return _production(row)

    def update_production_record(self, record_id: int, draft: ProductionDraft) -> ProductionRecord | None:
        row = self.session.get(ProductionRecordRow, record_id)
        if row is None:
            return None
        f = draft.fields
        row.quantity = f.quantity
        row.unit = f.unit
        row.period_start = f.period.start
        row.period_end = _stored_end(f.period)
        row.scope_key = f.scope_key
        row.reference = f.reference
        row.notes = f.notes
        self.session.flush()
        return _production(row)

    def delete_production_record(self, record_id: int) -> bool:
        row = self.session.get(ProductionRecordRow, record_id)
        if row is None:
            return False
        self.session.delete(row)
        self.session.flush()
        return True

    def get_production_record(self, record_id: int) -> ProductionRecord | None:
        row = self.session.get(ProductionRecordRow, record_id)
        return _production(row) if row else None

    def list_production_records(self, query: RecordQuery) -> list[ProductionRecord]:
        stmt = _filtered(select(ProductionRecordRow), ProductionRecordRow, query, has_category=False)
        return [_production(r) for r in self.session.scalars(stmt).all()]

    # ----------------------------------------------------------------- housekeeping
    def delete_records_by_source(self, source_type: str) -> tuple[int, int]:
        res = self.session.execute(
            delete(ResourceRecordRow).where(ResourceRecordRow.source_type == source_type)
        ).rowcount
        prod = self.session.execute(
            delete(ProductionRecordRow).where(ProductionRecordRow.source_type == source_type)
        ).rowcount
        self.session.flush()
        return int(res or 0), int(prod or 0)

    def count_records(self) -> RecordCounts:
        def count(model, demo: bool) -> int:
            stmt = select(func.count()).select_from(model)
            if demo:
                stmt = stmt.where(model.source_type == "demo")
            return int(self.session.scalar(stmt) or 0)

        return RecordCounts(
            resource=count(ResourceRecordRow, False),
            production=count(ProductionRecordRow, False),
            demo_resource=count(ResourceRecordRow, True),
            demo_production=count(ProductionRecordRow, True),
        )

    def get_preference(self, key: str) -> str | None:
        row = self.session.get(PreferenceRow, key)
        return row.value if row else None

    def set_preference(self, key: str, value: str | None) -> None:
        row = self.session.get(PreferenceRow, key)
        if value is None:
            if row is not None:
                self.session.delete(row)
        elif row is None:
            self.session.add(PreferenceRow(key=key, value=value))
        else:
            row.value = value
        self.session.flush()
