"""Engine creation, schema versioning and the unit of work (SQLite via SQLAlchemy).

Schema versioning uses SQLite's ``PRAGMA user_version``. Version 1 is the initial
schema. A database created by a *newer* version of the application, or a non-empty
file this application did not create, is refused instead of being modified.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import URL, Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from .exceptions import DatabaseVersionError, RepositoryError
from .models import Base
from .repositories import SqlRepository
from .services.category_service import seed_initial_categories

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

# Ordered upgrade steps: MIGRATIONS[n] upgrades a database from version n to n + 1.
MIGRATIONS: dict[int, callable] = {}


def create_sqlite_engine(path: Path | str) -> Engine:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        URL.create("sqlite", database=str(path)),
        connect_args={"check_same_thread": False},  # Streamlit runs scripts on worker threads
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record):  # pragma: no cover - exercised via integration tests
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.engine = create_sqlite_engine(self.path)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)

    # ------------------------------------------------------------------ schema
    def schema_version(self) -> int:
        with self.engine.connect() as conn:
            return int(conn.exec_driver_sql("PRAGMA user_version").scalar() or 0)

    def initialize(self) -> None:
        """Create or upgrade the schema; seed initial categories on first creation."""
        version = self.schema_version()
        existing_tables = set(inspect(self.engine).get_table_names())
        if version == 0:
            if existing_tables:
                raise DatabaseVersionError(
                    "This file is a database that Textile Resource Intelligence did not create. "
                    "Choose a different database location (TRI_DATABASE_PATH)."
                )
            Base.metadata.create_all(self.engine)
            self._set_version(SCHEMA_VERSION)
            with self.unit_of_work() as repo:
                seed_initial_categories(repo)
            logger.info("Created new database at %s", self.path)
            return
        if version > SCHEMA_VERSION:
            raise DatabaseVersionError(
                f"This database was created by a newer version of the application (schema {version}; "
                f"this version understands up to {SCHEMA_VERSION}). Update the application."
            )
        while version < SCHEMA_VERSION:
            MIGRATIONS[version](self.engine)
            version += 1
            self._set_version(version)

    def _set_version(self, version: int) -> None:
        with self.engine.connect() as conn:
            conn.exec_driver_sql(f"PRAGMA user_version = {int(version)}")
            conn.commit()

    # ---------------------------------------------------------- unit of work
    @contextmanager
    def unit_of_work(self) -> Iterator[SqlRepository]:
        """One transaction: commit on success, roll back if anything is raised."""
        session = self._sessions()
        try:
            yield SqlRepository(session)
            session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            logger.exception("Database operation failed")
            raise RepositoryError(
                "The database operation failed and no changes were saved. "
                "Check that the database file is writable and try again."
            ) from exc
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    def dispose(self) -> None:
        self.engine.dispose()
