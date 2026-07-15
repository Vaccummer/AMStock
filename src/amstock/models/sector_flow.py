"""ORM model for dated board-sector capital-flow snapshots."""

from __future__ import annotations

from decimal import Decimal  # noqa: TC003 -- SQLAlchemy resolves mapped annotations at runtime.

from sqlalchemy import Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from amstock.db.base import Base, EpochAuditMixin


class SectorFlowRecord(Base, EpochAuditMixin):
    """One sector snapshot for a trading date."""

    __tablename__ = "sector_flow_records"
    __table_args__ = (
        UniqueConstraint("flow_date", "sector_code", name="uq_sector_flow_date_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    flow_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    sector_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    sector_name: Mapped[str] = mapped_column(String(128), nullable=False)
    latest: Mapped[Decimal] = mapped_column(Numeric(28, 4), nullable=False)
    change_percent: Mapped[Decimal] = mapped_column(Numeric(28, 4), nullable=False)
    main_net_inflow_yuan: Mapped[Decimal] = mapped_column(Numeric(28, 4), nullable=False)
    auction_yuan: Mapped[Decimal] = mapped_column(Numeric(28, 4), nullable=False)
    super_order_inflow_yuan: Mapped[Decimal] = mapped_column(Numeric(28, 4), nullable=False)
    super_order_outflow_yuan: Mapped[Decimal] = mapped_column(Numeric(28, 4), nullable=False)
    super_order_net_yuan: Mapped[Decimal] = mapped_column(Numeric(28, 4), nullable=False)
    super_order_net_ratio: Mapped[Decimal] = mapped_column(Numeric(28, 4), nullable=False)
    large_order_inflow_yuan: Mapped[Decimal] = mapped_column(Numeric(28, 4), nullable=False)
    large_order_outflow_yuan: Mapped[Decimal] = mapped_column(Numeric(28, 4), nullable=False)
    large_order_net_yuan: Mapped[Decimal] = mapped_column(Numeric(28, 4), nullable=False)
    large_order_net_ratio: Mapped[Decimal] = mapped_column(Numeric(28, 4), nullable=False)
    medium_order_inflow_yuan: Mapped[Decimal] = mapped_column(Numeric(28, 4), nullable=False)
    medium_order_outflow_yuan: Mapped[Decimal] = mapped_column(Numeric(28, 4), nullable=False)
    medium_order_net_yuan: Mapped[Decimal] = mapped_column(Numeric(28, 4), nullable=False)
    medium_order_net_ratio: Mapped[Decimal] = mapped_column(Numeric(28, 4), nullable=False)
    small_order_inflow_yuan: Mapped[Decimal] = mapped_column(Numeric(28, 4), nullable=False)
    small_order_outflow_yuan: Mapped[Decimal] = mapped_column(Numeric(28, 4), nullable=False)
    small_order_net_yuan: Mapped[Decimal] = mapped_column(Numeric(28, 4), nullable=False)
    small_order_net_ratio: Mapped[Decimal] = mapped_column(Numeric(28, 4), nullable=False)
