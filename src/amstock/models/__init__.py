"""ORM model registry."""

from __future__ import annotations


def register_models() -> None:
    """Import ORM models so SQLAlchemy metadata is populated.

    Add model imports here as stock-domain tables are introduced.
    """
