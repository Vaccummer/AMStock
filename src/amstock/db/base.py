"""SQLAlchemy base classes."""

from __future__ import annotations

from sqlalchemy import Integer
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base for all ORM models."""


class EpochAuditMixin:
    """Common epoch audit columns."""

    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
