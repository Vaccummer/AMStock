"""Application service for dated full-market snapshots."""

from __future__ import annotations

import re
from dataclasses import fields
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from amstock.exceptions import ValidationError
from amstock.market_snapshot_io import MarketSnapshotInput
from amstock.repositories.market_snapshot import MarketSnapshotRepository

if TYPE_CHECKING:
    from amstock.db.engine import Database
    from amstock.models.market_snapshot import MarketSnapshotRecord
    from amstock.time import Clock

Order = Literal["asc", "desc"]

_TEXT_FIELDS = ("stock_code", "stock_name", "industry")
_NUMERIC_FIELDS = tuple(
    field.name for field in fields(MarketSnapshotInput) if field.name not in _TEXT_FIELDS
)
_SORT_FIELDS = frozenset((*_TEXT_FIELDS, *_NUMERIC_FIELDS))
_DISPLAY_FIELDS = (
    "total_volume",
    "current_volume",
    "amount_yuan",
    "order_difference",
    "inner_volume",
    "outer_volume",
    "bid_one_volume",
    "ask_one_volume",
    "total_shares",
    "total_market_cap_yuan",
    "circulating_shares",
    "circulating_market_cap_yuan",
)


class MarketSnapshotService:
    """Coordinate transactional imports and exact snapshot queries."""

    def __init__(self, *, database: Database, clock: Clock) -> None:
        self._database = database
        self._clock = clock

    def import_records(
        self, *, snapshot_date: str, records: list[MarketSnapshotInput]
    ) -> dict[str, object]:
        """Persist a non-empty parsed snapshot in one transaction."""

        normalized_date = validate_snapshot_date(snapshot_date)
        if not records:
            raise ValidationError("market snapshot file contains no records")
        with self._database.session() as session:
            counts = MarketSnapshotRepository(session).upsert_records(
                snapshot_date=normalized_date,
                records=records,
                now=self._clock.now_epoch(),
            )
            session.commit()
        return {
            "ok": True,
            "snapshot_date": normalized_date,
            "rows_read": len(records),
            "inserted": counts.inserted,
            "updated": counts.updated,
        }

    def list_records(
        self,
        *,
        snapshot_date: str,
        code: str | None = None,
        name: str | None = None,
        industry: str | None = None,
        min_change: Decimal | None = None,
        max_change: Decimal | None = None,
        min_turnover: Decimal | None = None,
        max_turnover: Decimal | None = None,
        min_pe: Decimal | None = None,
        max_pe: Decimal | None = None,
        min_market_cap: Decimal | None = None,
        max_market_cap: Decimal | None = None,
        sort_by: str = "stock_code",
        order: Order = "asc",
        limit: int = 100,
    ) -> dict[str, object]:
        """Return text-filtered rows with exact Decimal ranges and sorting."""

        normalized_date = validate_snapshot_date(snapshot_date)
        if sort_by not in _SORT_FIELDS:
            raise ValidationError(f"invalid sort_by: {sort_by}")
        if order not in {"asc", "desc"}:
            raise ValidationError("order must be asc or desc")
        if limit <= 0:
            raise ValidationError("limit must be positive")
        filters = (
            ("change_percent", min_change, max_change),
            ("turnover_percent", min_turnover, max_turnover),
            ("dynamic_pe", min_pe, max_pe),
            ("total_market_cap_yuan", min_market_cap, max_market_cap),
        )
        for field, minimum, maximum in filters:
            if minimum is not None and maximum is not None and minimum > maximum:
                raise ValidationError(f"minimum {field} cannot exceed maximum")

        with self._database.session() as session:
            records = MarketSnapshotRepository(session).list_records(
                snapshot_date=normalized_date,
                stock_code=_clean_filter(code),
                stock_name=_clean_filter(name),
                industry=_clean_filter(industry),
            )
            for field, minimum, maximum in filters:
                records = _range_filter(records, field, minimum, maximum)
            records = _sort_records(records, sort_by=sort_by, order=order)[:limit]
            return {
                "ok": True,
                "snapshot_date": normalized_date,
                "count": len(records),
                "records": [record_payload(record) for record in records],
            }


def validate_snapshot_date(value: str) -> str:
    """Accept only a real date in canonical YYYY-MM-DD form."""

    if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
        raise ValidationError("date must be in YYYY-MM-DD format")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValidationError("date must be in YYYY-MM-DD format") from exc


def _clean_filter(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _range_filter(
    records: list[MarketSnapshotRecord],
    field: str,
    minimum: Decimal | None,
    maximum: Decimal | None,
) -> list[MarketSnapshotRecord]:
    if minimum is None and maximum is None:
        return records
    filtered = []
    for record in records:
        value = getattr(record, field)
        if value is None:
            continue
        if minimum is not None and value < minimum:
            continue
        if maximum is not None and value > maximum:
            continue
        filtered.append(record)
    return filtered


def _sort_records(
    records: list[MarketSnapshotRecord], *, sort_by: str, order: Order
) -> list[MarketSnapshotRecord]:
    if sort_by == "stock_code":
        return sorted(records, key=lambda record: record.stock_code, reverse=order == "desc")
    present = [record for record in records if getattr(record, sort_by) is not None]
    missing = [record for record in records if getattr(record, sort_by) is None]
    present.sort(key=lambda record: record.stock_code)
    present.sort(key=lambda record: getattr(record, sort_by), reverse=order == "desc")
    missing.sort(key=lambda record: record.stock_code)
    return [*missing, *present] if order == "asc" else [*present, *missing]


def plain_decimal(value: Decimal) -> str:
    """Serialize without exponent notation or insignificant zeroes."""

    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def format_scaled(value: Decimal) -> str:
    """Render large base-unit values using 亿/万 without losing precision."""

    if abs(value) >= Decimal("100000000"):
        return f"{plain_decimal(value / Decimal('100000000'))}亿"
    if abs(value) >= Decimal("10000"):
        return f"{plain_decimal(value / Decimal('10000'))}万"
    return plain_decimal(value)


def record_payload(record: MarketSnapshotRecord) -> dict[str, object]:
    """Serialize every persisted source field and its useful display forms."""

    payload: dict[str, object] = {
        "id": record.id,
        "snapshot_date": record.snapshot_date,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }
    for field in fields(MarketSnapshotInput):
        value = getattr(record, field.name)
        payload[field.name] = plain_decimal(value) if isinstance(value, Decimal) else value
    for field in _DISPLAY_FIELDS:
        value = getattr(record, field)
        display_name = f"{field.removesuffix('_yuan')}_display"
        payload[display_name] = format_scaled(value) if value is not None else None
    return payload
