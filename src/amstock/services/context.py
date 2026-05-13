"""Application composition root."""

from __future__ import annotations

from dataclasses import dataclass

from amstock.config import AppSettings, load_settings
from amstock.db.engine import Database, create_database
from amstock.time import Clock, SystemClock


@dataclass(frozen=True, slots=True)
class ApplicationContext:
    """Objects shared by entry points."""

    settings: AppSettings
    database: Database
    clock: Clock


def create_application_context(settings: AppSettings | None = None) -> ApplicationContext:
    """Create the default application context."""

    resolved_settings = settings if settings is not None else load_settings()
    return ApplicationContext(
        settings=resolved_settings,
        database=create_database(resolved_settings),
        clock=SystemClock(),
    )
