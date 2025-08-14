from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
TEMPLATES_DIR = BASE_DIR / "app" / "templates"
STATIC_DIR = BASE_DIR / "app" / "static"
LOG_DIR = BASE_DIR / "logs"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(BASE_DIR / ".env"), env_prefix="PICKEMS_", case_sensitive=False)

    # App
    APP_NAME: str = "Office NFL Pickems"
    ENV: Literal["development", "production", "test"] = Field(default="development")
    LOG_LEVEL: str = Field(default="INFO")

    # Security / Sessions
    SECRET_KEY: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    SESSION_COOKIE_NAME: str = "pickems_session"
    SESSION_MAX_AGE: int = 60 * 60 * 24 * 14  # 14 days

    # Database
    DATABASE_URL: str = Field(default=f"sqlite:///{(DATA_DIR / 'app.db').as_posix()}")

    # Timezone for schedules and backups
    TIMEZONE: str = Field(default="local")

    # Backups
    BACKUPS_KEEP_LATEST: int = Field(default=12, description="How many latest backups to keep when pruning")

    # Live data cache
    LIVE_CACHE_TTL_SECONDS: int = Field(default=15, description="TTL for ESPN live cache (seconds)")
    LIVE_NEGATIVE_TTL_SECONDS: int = Field(default=600, description="TTL for ESPN live negative cache (seconds)")

    # Feature flags
    ENABLE_WEBSOCKETS: bool = True

    # NFL Data Provider settings
    # Provider key names are defined in app.services.nfl.factory
    NFL_PROVIDER: str = Field(default="espn")
    NFL_API_BASE: str | None = Field(default=None)
    NFL_API_KEY: str | None = Field(default=None)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()  # type: ignore[call-arg]

    # Ensure directories exist
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    return settings
