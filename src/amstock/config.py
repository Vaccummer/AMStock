"""Application configuration primitives."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_LANGUAGE = "zh-CN"
DEFAULT_TIMEZONE = "Asia/Shanghai"


@dataclass(frozen=True, slots=True)
class AppSettings:
    """Runtime settings shared by entry points and services."""

    database_url: str
    language: str = DEFAULT_LANGUAGE
    timezone: str = DEFAULT_TIMEZONE


def default_data_dir() -> Path:
    """Return the user-level data directory for the application."""

    return Path(os.environ.get("AMSTOCK_DATA_DIR", Path.home() / ".amstock"))


def default_database_url() -> str:
    """Return the default SQLite database URL."""

    return f"sqlite:///{default_data_dir() / 'amstock.sqlite3'}"


def load_settings() -> AppSettings:
    """Load settings from environment variables."""

    return AppSettings(
        database_url=os.environ.get("AMSTOCK_DATABASE_URL", default_database_url()),
        language=os.environ.get("AMSTOCK_LANGUAGE", DEFAULT_LANGUAGE),
        timezone=os.environ.get("AMSTOCK_TIMEZONE", DEFAULT_TIMEZONE),
    )
