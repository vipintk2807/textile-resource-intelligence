"""Application settings validated with Pydantic and read from TRI_* environment variables.

Settings control only local paths, logging and import limits. No setting enables any
network feature; the application makes no outbound connections of its own.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .paths import default_data_dir, default_database_path
from .schemas import ImportLimits

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class AppSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    database_path: Path
    data_dir: Path
    log_level: LogLevel = "INFO"
    max_import_megabytes: int = Field(default=5, ge=1, le=50)
    max_import_rows: int = Field(default=50_000, ge=1, le=500_000)
    page_size: int = Field(default=50, ge=10, le=500)

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper(cls, value):
        return value.upper() if isinstance(value, str) else value

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def log_file(self) -> Path:
        return self.data_dir / "logs" / "app.log"

    @property
    def import_limits(self) -> ImportLimits:
        return ImportLimits(max_bytes=self.max_import_megabytes * 1024 * 1024, max_rows=self.max_import_rows)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> AppSettings:
        env = os.environ if env is None else env
        database_path = default_database_path(env)
        data_dir = default_data_dir(env)
        if env.get("TRI_DATABASE_PATH"):
            data_dir = Path(env.get("TRI_DATA_DIR") or database_path.parent)
        values: dict[str, object] = {"database_path": database_path, "data_dir": data_dir}
        for key, name in (
            ("TRI_LOG_LEVEL", "log_level"),
            ("TRI_MAX_IMPORT_MB", "max_import_megabytes"),
            ("TRI_MAX_IMPORT_ROWS", "max_import_rows"),
            ("TRI_PAGE_SIZE", "page_size"),
        ):
            if env.get(key):
                values[name] = env[key]
        return cls(**values)


def configure_logging(settings: AppSettings) -> None:
    """Log to a rotating file in the data folder. Record contents are never logged."""
    root = logging.getLogger("textile_resource_intelligence")
    if any(getattr(h, "_tri_handler", False) for h in root.handlers):
        return
    settings.log_file.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        settings.log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler._tri_handler = True  # type: ignore[attr-defined]
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)
    root.setLevel(settings.log_level)
