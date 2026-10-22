"""Safe SQLite backups using SQLite's own online-backup API (standard library only).

Copying a database file while the application may be writing to it is not reliably
safe; the backup API produces a consistent snapshot.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path


def backup_database(database_path: Path, backup_dir: Path, now: datetime | None = None) -> Path:
    """Write a consistent copy of the database into ``backup_dir`` and verify it."""
    database_path = Path(database_path)
    if not database_path.is_file():
        raise FileNotFoundError("The database file does not exist yet, so there is nothing to back up.")
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    target = backup_dir / f"{database_path.stem}_backup_{stamp}.db"
    counter = 1
    while target.exists():
        target = backup_dir / f"{database_path.stem}_backup_{stamp}_{counter}.db"
        counter += 1

    source = sqlite3.connect(str(database_path))
    destination = sqlite3.connect(str(target))
    try:
        source.backup(destination)
        result = destination.execute("PRAGMA integrity_check").fetchone()
    finally:
        destination.close()
        source.close()
    if not result or result[0] != "ok":
        target.unlink(missing_ok=True)
        raise RuntimeError("The backup could not be verified and was discarded.")
    return target
