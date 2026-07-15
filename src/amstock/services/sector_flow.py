"""Application service for dated board-sector capital-flow snapshots."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from amstock.exceptions import ValidationError
from amstock.repositories.sector_flow import SectorFlowRepository

if TYPE_CHECKING:
    from amstock.db.engine import Database
    from amstock.models.sector_flow import SectorFlowRecord
    from amstock.sector_flow_io import SectorFlowInput
    from amstock.time import Clock

Direction = Literal["in", "out"]

_MONEY_FIELDS = (
    "main_net_inflow_yuan",
    "auction_yuan",
    "super_order_inflow_yuan",
    "super_order_outflow_yuan",
    "super_order_net_yuan",
    "large_order_inflow_yuan",
    "large_order_outflow_yuan",
    "large_order_net_yuan",
    "medium_order_inflow_yuan",
    "medium_order_outflow_yuan",
    "medium_order_net_yuan",
    "small_order_inflow_yuan",
    "small_order_outflow_yuan",
    "small_order_net_yuan",
)
_RATIO_FIELDS = (
    "super_order_net_ratio",
    "large_order_net_ratio",
    "medium_order_net_ratio",
    "small_order_net_ratio",
)


class SectorFlowService:
    """Coordinates transactional sector-flow imports and queries."""

    def __init__(self, *, database: Database, clock: Clock) -> None:
        self._database = database
        self._clock = clock

    def import_records(
        self,
        *,
        flow_date: str,
        records: list[SectorFlowInput],
    ) -> dict[str, object]:
        """Persist a complete parsed snapshot list in one transaction."""

        normalized_date = validate_flow_date(flow_date)
        if not records:
            raise ValidationError("sector flow file contains no records")
        with self._database.session() as session:
            written = SectorFlowRepository(session).upsert_records(
                flow_date=normalized_date,
                records=records,
                now=self._clock.now_epoch(),
            )
            session.commit()
        return {"ok": True, "flow_date": normalized_date, "count": written}

    def list_records(
        self,
        *,
        flow_date: str,
        sector_code: str | None,
        direction: Direction | None,
        limit: int | None,
    ) -> dict[str, object]:
        """Return date-filtered snapshots ordered by net inflow ascending."""

        normalized_date = validate_flow_date(flow_date)
        normalized_code = normalize_sector_code(sector_code) if sector_code is not None else None
        if direction not in {None, "in", "out"}:
            raise ValidationError("direction must be in or out")
        if limit is not None and limit <= 0:
            raise ValidationError("limit must be positive")
        with self._database.session() as session:
            records = SectorFlowRepository(session).list_records(
                flow_date=normalized_date,
                sector_code=normalized_code,
                direction=direction,
                limit=limit,
            )
            return {
                "ok": True,
                "flow_date": normalized_date,
                "count": len(records),
                "records": [record_payload(record) for record in records],
            }


def validate_flow_date(value: str) -> str:
    """Validate and normalize a YYYY-MM-DD sector-flow date."""

    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError) as exc:
        raise ValidationError("date must be in YYYY-MM-DD format") from exc


def normalize_sector_code(value: str) -> str:
    """Normalize a sector code used by the exact-match query."""

    normalized = value.strip()
    if not normalized:
        raise ValidationError("sector code is required")
    return normalized


def format_money_yuan(value: Decimal) -> str:
    """Render a yuan amount using the familiar 亿/万 units without precision loss."""

    if abs(value) >= Decimal("100000000"):
        return f"{plain_decimal(value / Decimal('100000000'))}亿"
    return f"{plain_decimal(value / Decimal('10000'))}万"


def plain_decimal(value: Decimal) -> str:
    """Serialize a Decimal without scientific notation or insignificant zeroes."""

    text = format(value, "f")
    if "." not in text:
        return text
    return text.rstrip("0").rstrip(".")


def record_payload(record: SectorFlowRecord) -> dict[str, object]:
    """Serialize a persisted snapshot for JSON output."""

    payload: dict[str, object] = {
        "id": record.id,
        "flow_date": record.flow_date,
        "sector_code": record.sector_code,
        "sector_name": record.sector_name,
        "latest": plain_decimal(record.latest),
        "change_percent": plain_decimal(record.change_percent),
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }
    for field in _MONEY_FIELDS:
        value = getattr(record, field)
        payload[field] = plain_decimal(value)
        payload[f"{field.removesuffix('_yuan')}_display"] = format_money_yuan(value)
    for field in _RATIO_FIELDS:
        payload[field] = plain_decimal(getattr(record, field))
    return payload
