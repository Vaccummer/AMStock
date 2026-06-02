"""ORM models for the local portfolio store."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from amstock.db.base import Base, EpochAuditMixin


class StoreUser(Base, EpochAuditMixin):
    """A local ledger user.

    Users are data labels only. The store CLI does not authenticate or authorize them.
    """

    __tablename__ = "store_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    transactions: Mapped[list[StoreTransaction]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class StoreTransaction(Base, EpochAuditMixin):
    """A buy, sell, or imported opening-position ledger entry."""

    __tablename__ = "store_transactions"
    __table_args__ = (
        UniqueConstraint("user_id", "id", name="uq_store_transactions_user_id_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("store_users.id"), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False)
    fee: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False, default=Decimal("0"))
    tax: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False, default=Decimal("0"))
    trade_date: Mapped[str] = mapped_column(String(10), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped[StoreUser] = relationship(back_populates="transactions")
