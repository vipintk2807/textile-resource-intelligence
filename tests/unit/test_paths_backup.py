"""Data location and safe backups (standard library only)."""

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from textile_resource_intelligence.backup import backup_database
from textile_resource_intelligence.paths import default_data_dir, default_database_path


def test_windows_default_is_under_localappdata():
    env = {"LOCALAPPDATA": r"C:\Users\Me\AppData\Local"}
    path = default_data_dir(env, "win32")
    assert path.name == "TextileResourceIntelligence" and "AppData" in str(path)
    assert default_database_path(env, "win32").name == "textile_resource_intelligence.db"


def test_overrides_take_precedence_and_do_not_depend_on_cwd():
    assert default_database_path({"TRI_DATABASE_PATH": "/tmp/x/custom.db"}, "linux") == Path("/tmp/x/custom.db")
    assert default_data_dir({"TRI_DATA_DIR": "/tmp/data"}, "win32") == Path("/tmp/data")
    assert default_database_path({"TRI_DATA_DIR": "/tmp/data"}, "linux") == Path("/tmp/data/textile_resource_intelligence.db")
    assert default_data_dir({}, "linux").is_absolute()


def test_backup_creates_a_verified_consistent_copy(tmp_path):
    db = tmp_path / "live.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE t (x INTEGER)")
    con.executemany("INSERT INTO t VALUES (?)", [(1,), (2,), (3,)])
    con.commit()
    con.close()
    target = backup_database(db, tmp_path / "backups", datetime(2025, 1, 2, 3, 4, 5))
    assert target.name == "live_backup_20250102_030405.db"
    copy = sqlite3.connect(target)
    assert copy.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 3
    copy.close()


def test_backup_never_overwrites_an_existing_backup(tmp_path):
    db = tmp_path / "live.db"
    sqlite3.connect(db).close()
    when = datetime(2025, 1, 2, 3, 4, 5)
    first = backup_database(db, tmp_path / "b", when)
    second = backup_database(db, tmp_path / "b", when)
    assert first != second and first.exists() and second.exists()


def test_backup_of_missing_database_fails_clearly(tmp_path):
    with pytest.raises(FileNotFoundError):
        backup_database(tmp_path / "missing.db", tmp_path / "b")
