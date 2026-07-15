"""ORM model registry."""

from __future__ import annotations


def register_models() -> None:
    """Import ORM models so SQLAlchemy metadata is populated.

    Add model imports here as stock-domain tables are introduced.
    """

    from amstock.models import sector_flow as _sector_flow  # noqa: F401
    from amstock.models import store as _store  # noqa: F401
