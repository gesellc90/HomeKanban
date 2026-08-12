"""Konfiguration aus .env, siehe docs/PLAN.md §8."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="HOMEKANBAN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Steckt in jedem gedruckten QR-Code (§8, R6). Mit dem Nutzer in M5 endgültig
    # festgelegt: eigener mDNS-Name statt des Pi-Hostnamens, damit die geklebten Etiketten auch
    # eine Umbenennung oder einen Hardwaretausch des Pi überleben.
    base_url: str = "http://homekanban.local:8181"
    port: int = 8181
    db_path: Path = Path("/data/homekanban.db")
    api_key: str | None = None
    undo_window_minutes: int = 10
    lead_days: int = 7
    backup_dir: Path = Path("/data/backups")
    backup_keep: str = "7d,4w"

    # Diese beiden Variablen tragen bewusst kein HOMEKANBAN_-Präfix (siehe docs/PLAN.md §8).
    tz: str = Field(default="Europe/Berlin", validation_alias="TZ")
    log_level: str = Field(default="info", validation_alias="LOG_LEVEL")

    @field_validator("db_path", mode="before")
    @classmethod
    def _db_path_must_be_set(cls, value: object) -> object:
        # Läuft vor der Path-Umwandlung: Path("") wird sonst stillschweigend zu Path(".").
        if isinstance(value, str) and not value.strip():
            raise ValueError("HOMEKANBAN_DB_PATH darf nicht leer sein")
        return value


def get_settings() -> Settings:
    return Settings()
