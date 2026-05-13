"""Import smoke tests for the project framework."""

from __future__ import annotations

from amstock.config import load_settings
from amstock.services import create_application_context


def test_load_settings() -> None:
    """Settings can be loaded without touching persistent storage."""

    settings = load_settings()

    assert settings.language
    assert settings.timezone


def test_create_application_context() -> None:
    """Application context can be composed."""

    context = create_application_context()

    assert context.settings.database_url
