"""ORM model for dated full-market snapshots."""

from __future__ import annotations

from decimal import Decimal  # noqa: TC003 -- SQLAlchemy resolves mapped annotations at runtime.

from sqlalchemy import Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from amstock.db.base import Base, EpochAuditMixin
from amstock.db.types import ExactDecimal


class MarketSnapshotRecord(Base, EpochAuditMixin):
    """One stock row from a full-market export for a trading date."""

    __tablename__ = "market_snapshot_records"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_date", "stock_code", name="uq_market_snapshot_date_code"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    stock_code: Mapped[str] = mapped_column(String(6), nullable=False, index=True)
    stock_name: Mapped[str] = mapped_column(String(128), nullable=False)
    industry: Mapped[str] = mapped_column(String(128), nullable=False)
    latest: Mapped[Decimal | None] = mapped_column(ExactDecimal(), nullable=True)
    change_percent: Mapped[Decimal | None] = mapped_column(ExactDecimal(), nullable=True)
    change_amount: Mapped[Decimal | None] = mapped_column(ExactDecimal(), nullable=True)
    total_volume: Mapped[Decimal | None] = mapped_column(ExactDecimal(), nullable=True)
    current_volume: Mapped[Decimal | None] = mapped_column(ExactDecimal(), nullable=True)
    bid_price: Mapped[Decimal | None] = mapped_column(ExactDecimal(), nullable=True)
    ask_price: Mapped[Decimal | None] = mapped_column(ExactDecimal(), nullable=True)
    speed_percent: Mapped[Decimal | None] = mapped_column(ExactDecimal(), nullable=True)
    turnover_percent: Mapped[Decimal | None] = mapped_column(ExactDecimal(), nullable=True)
    amount_yuan: Mapped[Decimal | None] = mapped_column(ExactDecimal(), nullable=True)
    dynamic_pe: Mapped[Decimal | None] = mapped_column(ExactDecimal(), nullable=True)
    high: Mapped[Decimal | None] = mapped_column(ExactDecimal(), nullable=True)
    low: Mapped[Decimal | None] = mapped_column(ExactDecimal(), nullable=True)
    open_price: Mapped[Decimal | None] = mapped_column(ExactDecimal(), nullable=True)
    previous_close: Mapped[Decimal | None] = mapped_column(ExactDecimal(), nullable=True)
    amplitude_percent: Mapped[Decimal | None] = mapped_column(ExactDecimal(), nullable=True)
    volume_ratio: Mapped[Decimal | None] = mapped_column(ExactDecimal(), nullable=True)
    order_ratio_percent: Mapped[Decimal | None] = mapped_column(ExactDecimal(), nullable=True)
    order_difference: Mapped[Decimal | None] = mapped_column(ExactDecimal(), nullable=True)
    average_price: Mapped[Decimal | None] = mapped_column(ExactDecimal(), nullable=True)
    inner_volume: Mapped[Decimal | None] = mapped_column(ExactDecimal(), nullable=True)
    outer_volume: Mapped[Decimal | None] = mapped_column(ExactDecimal(), nullable=True)
    inner_outer_ratio: Mapped[Decimal | None] = mapped_column(ExactDecimal(), nullable=True)
    bid_one_volume: Mapped[Decimal | None] = mapped_column(ExactDecimal(), nullable=True)
    ask_one_volume: Mapped[Decimal | None] = mapped_column(ExactDecimal(), nullable=True)
    pb: Mapped[Decimal | None] = mapped_column(ExactDecimal(), nullable=True)
    total_shares: Mapped[Decimal | None] = mapped_column(ExactDecimal(), nullable=True)
    total_market_cap_yuan: Mapped[Decimal | None] = mapped_column(ExactDecimal(), nullable=True)
    circulating_shares: Mapped[Decimal | None] = mapped_column(ExactDecimal(), nullable=True)
    circulating_market_cap_yuan: Mapped[Decimal | None] = mapped_column(
        ExactDecimal(), nullable=True
    )
    change_3d_percent: Mapped[Decimal | None] = mapped_column(ExactDecimal(), nullable=True)
    change_6d_percent: Mapped[Decimal | None] = mapped_column(ExactDecimal(), nullable=True)
    turnover_3d_percent: Mapped[Decimal | None] = mapped_column(ExactDecimal(), nullable=True)
    turnover_6d_percent: Mapped[Decimal | None] = mapped_column(ExactDecimal(), nullable=True)
    consecutive_up_days: Mapped[Decimal | None] = mapped_column(ExactDecimal(), nullable=True)
    month_change_percent: Mapped[Decimal | None] = mapped_column(ExactDecimal(), nullable=True)
    year_change_percent: Mapped[Decimal | None] = mapped_column(ExactDecimal(), nullable=True)
    one_month_change_percent: Mapped[Decimal | None] = mapped_column(
        ExactDecimal(), nullable=True
    )
    one_year_change_percent: Mapped[Decimal | None] = mapped_column(
        ExactDecimal(), nullable=True
    )
