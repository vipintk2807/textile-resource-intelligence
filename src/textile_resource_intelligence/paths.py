"""Where the application keeps its local data (standard library only).

The location never depends on the current working directory, so starting the app from
different folders cannot create several unrelated databases.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path

APP_DIR_NAME = "TextileResourceIntelligence"
DATABASE_FILENAME = "textile_resource_intelligence.db"


def default_data_dir(env: Mapping[str, str] | None = None, platform: str | None = None) -> Path:
    """``%LOCALAPPDATA%\\TextileResourceIntelligence`` on Windows (override: TRI_DATA_DIR)."""
    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform
    override = env.get("TRI_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if platform.startswith("win"):
        base = env.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    else:
        base = env.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / APP_DIR_NAME


def default_database_path(env: Mapping[str, str] | None = None, platform: str | None = None) -> Path:
    """Database file path (override: TRI_DATABASE_PATH)."""
    env = os.environ if env is None else env
    override = env.get("TRI_DATABASE_PATH")
    if override:
        return Path(override).expanduser()
    return default_data_dir(env, platform) / DATABASE_FILENAME
