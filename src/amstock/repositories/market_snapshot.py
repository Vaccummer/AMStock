"""Database queries for dated full-market snapshots."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import TYPE_CHECKING

from sqlalchemy import select

from amstock.market_snapshot_io import MarketSnapshotInput
from amstock.models.market_snapshot import MarketSnapshotRecord

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


_SNAPSHOT_FIELDS = tuple(field.name for field in fields(MarketSnapshotInput))


@dataclass(frozen=True, slots=True)
class UpsertCounts:
    """Counts of inserted and updated stock snapshots."""

    inserted: int
    updated: int


class MarketSnapshotRepository:
    """Read and write full-market snapshots in the current unit of work."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_records(
        self,
        *,
        snapshot_date: str,
        records: list[MarketSnapshotInput],
        now: int,
    ) -> UpsertCounts:
        """Upsert supplied rows after loading all existing codes for the date once."""

        existing = {
            row.stock_code: row
            for row in self._session.scalars(
                select(MarketSnapshotRecord).where(
                    MarketSnapshotRecord.snapshot_date == snapshot_date
                )
            )
        }
        inserted = 0
        updated = 0
        for snapshot in records:
            stored = existing.get(snapshot.stock_code)
            if stored is None:
                self._session.add(
                    MarketSnapshotRecord(
                        snapshot_date=snapshot_date,
                        created_at=now,
                        updated_at=None,
                        **_snapshot_values(snapshot),
                    )
                )
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
        snapshot_date: str,
        stock_code: str | None,
        stock_name: str | None,
        industry: str | None,
    ) -> list[MarketSnapshotRecord]:
        """Apply date and text filters in SQL before exact numeric processing."""

        statement = select(MarketSnapshotRecord).where(
            MarketSnapshotRecord.snapshot_date == snapshot_date
        )
        if stock_code is not None:
            statement = statement.where(MarketSnapshotRecord.stock_code == stock_code)
        if stock_name is not None:
            statement = statement.where(MarketSnapshotRecord.stock_name.contains(stock_name))
        if industry is not None:
            statement = statement.where(MarketSnapshotRecord.industry.contains(industry))
        return list(self._session.scalars(statement))


def _snapshot_values(snapshot: MarketSnapshotInput) -> dict[str, object]:
    return {field: getattr(snapshot, field) for field in _SNAPSHOT_FIELDS}
