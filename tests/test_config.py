from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings


def test_defaults_match_plan_section_8() -> None:
    settings = Settings(_env_file=None)

    assert settings.base_url == "http://raspberrypi.local:8181"
    assert settings.port == 8181
    assert settings.db_path == Path("/data/homekanban.db")
    assert settings.api_key is None
    assert settings.undo_window_minutes == 10
    assert settings.lead_days == 7
    assert settings.backup_dir == Path("/data/backups")
    assert settings.backup_keep == "7d,4w"
    assert settings.tz == "Europe/Berlin"
    assert settings.log_level == "info"


def test_reads_prefixed_and_unprefixed_variables_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOMEKANBAN_PORT", "9000")
    monkeypatch.setenv("HOMEKANBAN_DB_PATH", "/tmp/homekanban-test.db")
    monkeypatch.setenv("TZ", "UTC")
    monkeypatch.setenv("LOG_LEVEL", "debug")

    settings = Settings(_env_file=None)

    assert settings.port == 9000
    assert settings.db_path == Path("/tmp/homekanban-test.db")
    assert settings.tz == "UTC"
    assert settings.log_level == "debug"


def test_rejects_empty_db_path() -> None:
    with pytest.raises(ValueError, match="HOMEKANBAN_DB_PATH"):
        Settings(_env_file=None, db_path="")
