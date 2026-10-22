"""Real SQLite persistence via SQLAlchemy. Skipped automatically if SQLAlchemy is missing."""

import sqlite3
from datetime import date
from decimal import Decimal as D

import pytest

pytest.importorskip("sqlalchemy")

from textile_resource_intelligence.backup import backup_database  # noqa: E402
from textile_resource_intelligence.database import SCHEMA_VERSION, Database  # noqa: E402
from textile_resource_intelligence.domain.types import Period, ValidatedFields  # noqa: E402
from textile_resource_intelligence.exceptions import DatabaseVersionError, RepositoryError  # noqa: E402
from textile_resource_intelligence.schemas import RecordQuery, ResourceDraft  # noqa: E402


def _fields(quantity="1200", period=None):
    return ValidatedFields(D(quantity), "kWh", period or Period(date(2025, 1, 1), date(2025, 1, 31)), None, None, None)


def test_first_start_creates_schema_version_and_seeds_categories(tmp_path):
    db = Database(tmp_path / "a.db")
    db.initialize()
    assert db.schema_version() == SCHEMA_VERSION
    with db.unit_of_work() as repo:
        names = [c.name for c in repo.list_categories()]
        assert repo.count_records().total == 0  # no fictional records on first launch
    assert names == ["Electricity", "Water", "Chemicals", "Steam", "Fuel", "Waste", "Other resources"]
    db.dispose()


def test_initialising_twice_does_not_duplicate_seed_data(tmp_path):
    db = Database(tmp_path / "a.db")
    db.initialize()
    db.initialize()
    with db.unit_of_work() as repo:
        assert len(repo.list_categories()) == 7
    db.dispose()


def test_data_survives_a_restart_with_exact_decimals(tmp_path):
    path = tmp_path / "a.db"
    db = Database(path)
    db.initialize()
    with db.unit_of_work() as repo:
        repo.add_resource_record(ResourceDraft(1, _fields("0.1")))
    db.dispose()
    again = Database(path)
    again.initialize()
    with again.unit_of_work() as repo:
        (rec,) = repo.list_resource_records(RecordQuery())
    assert rec.quantity == D("0.1") and isinstance(rec.quantity, D)
    assert rec.period == Period(date(2025, 1, 1), date(2025, 1, 31))
    again.dispose()


def test_single_date_is_stored_as_null_end_and_read_back_as_equal_dates(tmp_path):
    path = tmp_path / "a.db"
    db = Database(path)
    db.initialize()
    day = Period(date(2025, 3, 5), date(2025, 3, 5))
    with db.unit_of_work() as repo:
        rec = repo.add_resource_record(ResourceDraft(1, _fields(period=day)))
    raw = sqlite3.connect(path).execute("SELECT period_end FROM resource_records").fetchone()
    assert raw == (None,) and rec.period == day
    db.dispose()


def test_exception_inside_unit_of_work_rolls_everything_back(tmp_path):
    db = Database(tmp_path / "a.db")
    db.initialize()
    with pytest.raises(RuntimeError):
        with db.unit_of_work() as repo:
            repo.add_resource_record(ResourceDraft(1, _fields()))
            raise RuntimeError("boom")
    with db.unit_of_work() as repo:
        assert repo.count_records().resource == 0
    db.dispose()


def test_foreign_key_to_a_missing_category_is_rejected(tmp_path):
    db = Database(tmp_path / "a.db")
    db.initialize()
    with pytest.raises(RepositoryError):
        with db.unit_of_work() as repo:
            repo.add_resource_record(ResourceDraft(999, _fields()))
    db.dispose()


def test_database_constraints_reject_negative_quantities(tmp_path):
    db = Database(tmp_path / "a.db")
    db.initialize()
    with pytest.raises(RepositoryError):
        with db.unit_of_work() as repo:
            repo.add_resource_record(ResourceDraft(1, _fields("-5")))
    db.dispose()


def test_newer_schema_is_refused_without_modification(tmp_path):
    path = tmp_path / "a.db"
    Database(path).initialize()
    con = sqlite3.connect(path)
    con.execute("PRAGMA user_version = 99")
    con.commit()
    con.close()
    with pytest.raises(DatabaseVersionError, match="newer"):
        Database(path).initialize()


def test_unrelated_existing_database_is_refused(tmp_path):
    path = tmp_path / "other.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE something_else (x INTEGER)")
    con.commit()
    con.close()
    with pytest.raises(DatabaseVersionError, match="did not create"):
        Database(path).initialize()


def test_backup_of_a_live_database_contains_the_records(tmp_path):
    db = Database(tmp_path / "a.db")
    db.initialize()
    with db.unit_of_work() as repo:
        repo.add_resource_record(ResourceDraft(1, _fields()))
    target = backup_database(db.path, tmp_path / "backups")
    copy = sqlite3.connect(target)
    assert copy.execute("SELECT COUNT(*) FROM resource_records").fetchone()[0] == 1
    copy.close()
    db.dispose()


def test_text_search_treats_wildcards_literally(tmp_path):
    db = Database(tmp_path / "a.db")
    db.initialize()
    with db.unit_of_work() as repo:
        repo.add_resource_record(ResourceDraft(1, ValidatedFields(D(1), "kWh", Period(date(2025, 1, 1), date(2025, 1, 1)), None, "100%_done", None)))
        repo.add_resource_record(ResourceDraft(1, ValidatedFields(D(2), "kWh", Period(date(2025, 1, 2), date(2025, 1, 2)), None, "other", None)))
        assert len(repo.list_resource_records(RecordQuery(text="%"))) == 1
        assert len(repo.list_resource_records(RecordQuery(text="_done"))) == 1
    db.dispose()
