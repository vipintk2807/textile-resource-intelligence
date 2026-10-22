"""In-memory implementation of the Repository port, used as a test double.

It mirrors the SQL repository's behaviour (filters, ordering, uniqueness) and the
unit of work rolls back by restoring a snapshot, so service-level transaction
behaviour can be tested without a database. The same service tests also run
against the real SQLite repository (see conftest.py).
"""

from __future__ import annotations

import copy
from contextlib import contextmanager

from textile_resource_intelligence.domain.types import (
    Category,
    ProductionRecord,
    ResourceRecord,
)
from textile_resource_intelligence.exceptions import RepositoryError
from textile_resource_intelligence.schemas import (
    CategoryDraft,
    ProductionDraft,
    RecordCounts,
    RecordQuery,
    ResourceDraft,
)


class MemoryState:
    def __init__(self) -> None:
        self.categories: dict[int, Category] = {}
        self.resources: dict[int, ResourceRecord] = {}
        self.production: dict[int, ProductionRecord] = {}
        self.preferences: dict[str, str] = {}
        self.next_id = {"category": 1, "resource": 1, "production": 1}
        self.fail_on_resource_insert_number: int | None = None  # fault injection
        self._resource_inserts = 0


def _matches(record, query: RecordQuery, *, has_category: bool) -> bool:
    if query.date_from is not None and record.period.end < query.date_from:
        return False
    if query.date_to is not None and record.period.start > query.date_to:
        return False
    if has_category and query.category_id is not None and record.category_id != query.category_id:
        return False
    if query.scope_mode == "overall" and record.scope_key is not None:
        return False
    if query.scope_mode == "key" and record.scope_key != query.scope_key:
        return False
    if query.source_type and record.source_type != query.source_type:
        return False
    if query.text:
        needle = query.text.casefold()
        hay = " ".join(x for x in (record.reference, record.notes, record.scope_key) if x).casefold()
        if needle not in hay:
            return False
    return True


class MemoryRepository:
    def __init__(self, state: MemoryState) -> None:
        self.s = state

    # categories
    def list_categories(self):
        return sorted(self.s.categories.values(), key=lambda c: c.id)

    def get_category(self, category_id):
        return self.s.categories.get(category_id)

    def find_category_by_name(self, name):
        for c in self.s.categories.values():
            if c.name.casefold() == name.casefold():
                return c
        return None

    def add_category(self, draft: CategoryDraft):
        cid = self.s.next_id["category"]
        self.s.next_id["category"] += 1
        c = Category(cid, draft.name, draft.resource_type, draft.default_unit,
                     tuple(draft.allowed_units), draft.is_active)
        self.s.categories[cid] = c
        return c

    def update_category(self, category_id, draft: CategoryDraft):
        if category_id not in self.s.categories:
            return None
        c = Category(category_id, draft.name, draft.resource_type, draft.default_unit,
                     tuple(draft.allowed_units), draft.is_active)
        self.s.categories[category_id] = c
        return c

    def count_resource_records_in_category(self, category_id):
        return sum(1 for r in self.s.resources.values() if r.category_id == category_id)

    # resource
    def add_resource_record(self, draft: ResourceDraft):
        self.s._resource_inserts += 1
        if self.s.fail_on_resource_insert_number == self.s._resource_inserts:
            raise RepositoryError("Injected failure")
        if draft.category_id not in self.s.categories:
            raise RepositoryError("Foreign key violation")
        rid = self.s.next_id["resource"]
        self.s.next_id["resource"] += 1
        f = draft.fields
        r = ResourceRecord(rid, draft.category_id, f.quantity, f.unit, f.period, f.scope_key,
                           f.reference, f.notes, draft.source_type, f.record_type)
        self.s.resources[rid] = r
        return r

    def update_resource_record(self, record_id, draft: ResourceDraft):
        if record_id not in self.s.resources:
            return None
        f = draft.fields
        r = ResourceRecord(record_id, draft.category_id, f.quantity, f.unit, f.period, f.scope_key,
                           f.reference, f.notes, draft.source_type, f.record_type)
        self.s.resources[record_id] = r
        return r

    def delete_resource_record(self, record_id):
        return self.s.resources.pop(record_id, None) is not None

    def get_resource_record(self, record_id):
        return self.s.resources.get(record_id)

    def list_resource_records(self, query: RecordQuery):
        rows = [r for r in self.s.resources.values() if _matches(r, query, has_category=True)]
        return sorted(rows, key=lambda r: (r.period.start, r.id))

    # production
    def add_production_record(self, draft: ProductionDraft):
        pid = self.s.next_id["production"]
        self.s.next_id["production"] += 1
        f = draft.fields
        r = ProductionRecord(pid, f.quantity, f.unit, f.period, f.scope_key, f.reference,
                             f.notes, draft.source_type)
        self.s.production[pid] = r
        return r

    def update_production_record(self, record_id, draft: ProductionDraft):
        if record_id not in self.s.production:
            return None
        f = draft.fields
        r = ProductionRecord(record_id, f.quantity, f.unit, f.period, f.scope_key, f.reference,
                             f.notes, draft.source_type)
        self.s.production[record_id] = r
        return r

    def delete_production_record(self, record_id):
        return self.s.production.pop(record_id, None) is not None

    def get_production_record(self, record_id):
        return self.s.production.get(record_id)

    def list_production_records(self, query: RecordQuery):
        rows = [r for r in self.s.production.values() if _matches(r, query, has_category=False)]
        return sorted(rows, key=lambda r: (r.period.start, r.id))

    # housekeeping
    def delete_records_by_source(self, source_type):
        res = [i for i, r in self.s.resources.items() if r.source_type == source_type]
        prod = [i for i, r in self.s.production.items() if r.source_type == source_type]
        for i in res:
            del self.s.resources[i]
        for i in prod:
            del self.s.production[i]
        return len(res), len(prod)

    def count_records(self):
        return RecordCounts(
            resource=len(self.s.resources),
            production=len(self.s.production),
            demo_resource=sum(1 for r in self.s.resources.values() if r.source_type == "demo"),
            demo_production=sum(1 for r in self.s.production.values() if r.source_type == "demo"),
        )

    def get_preference(self, key):
        return self.s.preferences.get(key)

    def set_preference(self, key, value):
        if value is None:
            self.s.preferences.pop(key, None)
        else:
            self.s.preferences[key] = value


def make_memory_uow(state: MemoryState):
    @contextmanager
    def uow():
        snapshot = copy.deepcopy(
            (state.categories, state.resources, state.production, state.preferences, state.next_id)
        )
        try:
            yield MemoryRepository(state)
        except BaseException:
            (state.categories, state.resources, state.production, state.preferences, state.next_id) = snapshot
            raise

    return uow

