"""Wires the database and all services together once per application process."""

from __future__ import annotations

from dataclasses import dataclass

from ..config import AppSettings
from ..database import Database
from .analysis_service import AnalysisService
from .category_service import CategoryService
from .demo_service import DemoService
from .export_service import ExportService
from .import_service import ImportService
from .preferences_service import PreferencesService
from .production_service import ProductionService
from .resource_service import ResourceService


@dataclass
class AppContainer:
    settings: AppSettings
    database: Database
    categories: CategoryService
    resources: ResourceService
    production: ProductionService
    imports: ImportService
    analysis: AnalysisService
    exports: ExportService
    preferences: PreferencesService
    demo: DemoService


def build_container(settings: AppSettings) -> AppContainer:
    """Open (and create or upgrade) the database and build every service."""
    database = Database(settings.database_path)
    database.initialize()
    uow = database.unit_of_work
    analysis = AnalysisService(uow)
    return AppContainer(
        settings=settings,
        database=database,
        categories=CategoryService(uow),
        resources=ResourceService(uow),
        production=ProductionService(uow),
        imports=ImportService(uow, settings.import_limits),
        analysis=analysis,
        exports=ExportService(uow, analysis),
        preferences=PreferencesService(uow),
        demo=DemoService(uow),
    )
