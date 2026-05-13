"""Database smoke tests."""

from __future__ import annotations

from amstock.config import AppSettings
from amstock.services import create_application_context


def test_create_schema_for_sqlite_memory() -> None:
    """The base schema can be created before stock-domain models exist."""

    context = create_application_context(AppSettings(database_url="sqlite+pysqlite:///:memory:"))

    context.database.create_schema()
