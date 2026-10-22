"""Shared fixtures.

``uow_factory`` runs every service test twice: against an in-memory repository and,
when SQLAlchemy is installed, against a real temporary SQLite database. Tests never
touch the user's real database.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from textile_resource_intelligence.schemas import ImportLimits
from textile_resource_intelligence.services.analysis_service import AnalysisService
from textile_resource_intelligence.services.category_service import CategoryService, seed_initial_categories
from textile_resource_intelligence.services.demo_service import DemoService
from textile_resource_intelligence.services.export_service import ExportService
from textile_resource_intelligence.services.import_service import ImportService
from textile_resource_intelligence.services.preferences_service import PreferencesService
from textile_resource_intelligence.services.production_service import ProductionService
from textile_resource_intelligence.services.resource_service import ResourceService
from tests.support.memory_repository import MemoryState, make_memory_uow

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@dataclass
class Services:
    uow: object
    categories: CategoryService
    resources: ResourceService
    production: ProductionService
    imports: ImportService
    analysis: AnalysisService
    exports: ExportService
    preferences: PreferencesService
    demo: DemoService

    def category_id(self, name: str) -> int:
        for c in self.categories.list():
            if c.name == name:
                return c.id
        raise KeyError(name)


def build_services(uow, limits: ImportLimits | None = None) -> Services:
    analysis = AnalysisService(uow)
    return Services(
        uow=uow,
        categories=CategoryService(uow),
        resources=ResourceService(uow),
        production=ProductionService(uow),
        imports=ImportService(uow, limits),
        analysis=analysis,
        exports=ExportService(uow, analysis),
        preferences=PreferencesService(uow),
        demo=DemoService(uow),
    )


@pytest.fixture
def fixture_dir() -> Path:
    return FIXTURE_DIR


@pytest.fixture
def memory_state():
    return MemoryState()


@pytest.fixture(params=["memory", "sqlite"])
def uow_factory(request, tmp_path):
    if request.param == "memory":
        state = MemoryState()
        uow = make_memory_uow(state)
        with uow() as repo:
            seed_initial_categories(repo)
        yield uow
    else:
        pytest.importorskip("sqlalchemy")
        from textile_resource_intelligence.database import Database

        db = Database(tmp_path / "test.db")
        db.initialize()
        yield db.unit_of_work
        db.dispose()


@pytest.fixture
def services(uow_factory) -> Services:
    return build_services(uow_factory)
