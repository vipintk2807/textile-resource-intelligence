"""Settings validation (Pydantic)."""

from pathlib import Path

import pytest

pytest.importorskip("pydantic")

from pydantic import ValidationError  # noqa: E402

from textile_resource_intelligence.config import AppSettings  # noqa: E402


def test_defaults_come_from_the_standard_data_folder():
    settings = AppSettings.from_env({"TRI_DATA_DIR": "/tmp/tri"})
    assert settings.database_path == Path("/tmp/tri/textile_resource_intelligence.db")
    assert settings.backup_dir == Path("/tmp/tri/backups") and settings.log_file == Path("/tmp/tri/logs/app.log")
    assert settings.import_limits.max_bytes == 5 * 1024 * 1024 and settings.log_level == "INFO"


def test_database_override_keeps_backups_beside_it():
    settings = AppSettings.from_env({"TRI_DATABASE_PATH": "/tmp/x/custom.db"})
    assert settings.database_path == Path("/tmp/x/custom.db") and settings.backup_dir == Path("/tmp/x/backups")


def test_environment_overrides_are_validated():
    settings = AppSettings.from_env({"TRI_DATA_DIR": "/tmp/t", "TRI_LOG_LEVEL": "debug", "TRI_MAX_IMPORT_MB": "10"})
    assert settings.log_level == "DEBUG" and settings.import_limits.max_bytes == 10 * 1024 * 1024


@pytest.mark.parametrize("env", [{"TRI_LOG_LEVEL": "chatty"}, {"TRI_MAX_IMPORT_MB": "0"},
                                 {"TRI_MAX_IMPORT_ROWS": "abc"}, {"TRI_PAGE_SIZE": "1"}])
def test_invalid_settings_are_rejected(env):
    with pytest.raises(ValidationError):
        AppSettings.from_env({"TRI_DATA_DIR": "/tmp/t", **env})
