"""Database queries for board-sector capital-flow snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select

from amstock.models.sector_flow import SectorFlowRecord

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from amstock.sector_flow_io import SectorFlowInput


_SNAPSHOT_FIELDS = (
    "sector_name",
    "latest",
    "change_percent",
    "main_net_inflow_yuan",
    "auction_yuan",
    "super_order_inflow_yuan",
    "super_order_outflow_yuan",
    "super_order_net_yuan",
    "super_order_net_ratio",
    "large_order_inflow_yuan",
    "large_order_outflow_yuan",
    "large_order_net_yuan",
    "large_order_net_ratio",
    "medium_order_inflow_yuan",
    "medium_order_outflow_yuan",
    "medium_order_net_yuan",
    "medium_order_net_ratio",
    "small_order_inflow_yuan",
    "small_order_outflow_yuan",
    "small_order_net_yuan",
    "small_order_net_ratio",
)


@dataclass(frozen=True, slots=True)
class UpsertCounts:
    """Counts of inserted and updated sector snapshots."""

    inserted: int
    updated: int


class SectorFlowRepository:
    """Read and write sector-flow snapshots in the current unit of work."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_records(
        self,
        *,
        flow_date: str,
        records: list[SectorFlowInput],
        now: int,
    ) -> UpsertCounts:
        """Insert or update each supplied date-and-sector snapshot without deleting others."""

        inserted = 0
        updated = 0
        for snapshot in records:
            stored = self._session.scalar(
                select(SectorFlowRecord).where(
                    SectorFlowRecord.flow_date == flow_date,
                    SectorFlowRecord.sector_code == snapshot.sector_code,
                )
            )
            if stored is None:
                stored = SectorFlowRecord(
                    flow_date=flow_date,
                    sector_code=snapshot.sector_code,
                    created_at=now,
                    updated_at=None,
                    **_snapshot_values(snapshot),
                )
                self._session.add(stored)
                inserted += 1
                continue

            for field, value in _snapshot_values(snapshot).items():
                setattr(stored, field, value)
            stored.updated_at = now
            updated += 1

        self._session.flush()
        return UpsertCounts(inserted=inserted, updated=updated)

    def list_records(
        self,
        *,
        flow_date: str,
        sector_code: str | None,
    ) -> list[SectorFlowRecord]:
        """Load a small dated dataset with an optional exact code filter."""

        statement = select(SectorFlowRecord).where(SectorFlowRecord.flow_date == flow_date)
        if sector_code is not None:
            statement = statement.where(SectorFlowRecord.sector_code == sector_code)
        return list(self._session.scalars(statement))


def _snapshot_values(snapshot: SectorFlowInput) -> dict[str, object]:
    """Return all mutable ORM fields from a complete parsed snapshot."""

    return {field: getattr(snapshot, field) for field in _SNAPSHOT_FIELDS}
