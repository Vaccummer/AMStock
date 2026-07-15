"""Tests for dated sector-flow persistence and queries."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from amstock.config import AppSettings
from amstock.exceptions import ValidationError
from amstock.models.sector_flow import SectorFlowRecord
from amstock.sector_flow_io import SectorFlowInput, parse_money_to_yuan
from amstock.services import create_application_context
from amstock.services.sector_flow import SectorFlowService
from amstock.time import FixedClock


def create_service() -> SectorFlowService:
    """Create a service backed by an isolated in-memory database."""

    context = create_application_context(AppSettings(database_url="sqlite+pysqlite:///:memory:"))
    context.database.create_schema()
    return SectorFlowService(database=context.database, clock=FixedClock(1_800_000_000))


def record(sector_code: str, main_net_inflow: str) -> SectorFlowInput:
    """Build a complete parsed snapshot for persistence tests."""

    zero = Decimal("0")
    return SectorFlowInput(
        sector_code=sector_code,
        sector_name=f"Sector {sector_code}",
        latest=Decimal("123.45"),
        change_percent=Decimal("1.25"),
        main_net_inflow_yuan=parse_money_to_yuan(main_net_inflow, line_number=1),
        auction_yuan=zero,
        super_order_inflow_yuan=zero,
        super_order_outflow_yuan=zero,
        super_order_net_yuan=zero,
        super_order_net_ratio=zero,
        large_order_inflow_yuan=zero,
        large_order_outflow_yuan=zero,
        large_order_net_yuan=zero,
        large_order_net_ratio=zero,
        medium_order_inflow_yuan=zero,
        medium_order_outflow_yuan=zero,
        medium_order_net_yuan=zero,
        medium_order_net_ratio=zero,
        small_order_inflow_yuan=zero,
        small_order_outflow_yuan=zero,
        small_order_net_yuan=zero,
        small_order_net_ratio=zero,
    )


def test_import_upserts_same_date_and_lists_outflows_first() -> None:
    """A repeated code updates its snapshot and absent codes remain available."""

    service = create_service()
    service.import_records(
        flow_date="2026-07-15",
        records=[record("BK1", "10万"), record("BK2", "-2亿")],
    )
    service.import_records(flow_date="2026-07-15", records=[record("BK1", "-2355万")])

    result = service.list_records(
        flow_date="2026-07-15", sector_code=None, direction="out", limit=None
    )

    assert result["count"] == 2
    assert [item["sector_code"] for item in result["records"]] == ["BK2", "BK1"]
    assert result["records"][1]["main_net_inflow_yuan"] == "-23550000"
    assert result["records"][0]["main_net_inflow_display"] == "-2亿"


def test_import_does_not_write_when_validation_prevents_intermediate_table() -> None:
    """An empty parsed snapshot list is rejected before a transaction is opened."""

    service = create_service()

    with pytest.raises(ValidationError, match="sector flow file contains no records"):
        service.import_records(flow_date="2026-07-15", records=[])

    result = service.list_records(
        flow_date="2026-07-15", sector_code=None, direction=None, limit=None
    )
    assert result["count"] == 0


def test_list_filters_inflows_and_rejects_non_positive_limits() -> None:
    """Direction and limit validation are applied to the dated query."""

    service = create_service()
    service.import_records(
        flow_date="2026-07-15",
        records=[record("BK1", "10万"), record("BK2", "-2亿"), record("BK3", "0万")],
    )

    result = service.list_records(
        flow_date="2026-07-15", sector_code=None, direction="in", limit=1
    )

    assert result["count"] == 1
    assert result["records"][0]["sector_code"] == "BK1"
    with pytest.raises(ValidationError, match="limit must be positive"):
        service.list_records(
            flow_date="2026-07-15", sector_code=None, direction=None, limit=0
        )


def test_import_preserves_sub_cent_yuan_precision_after_database_round_trip() -> None:
    """SQLite retains parsed yuan values below the former four-decimal storage scale."""

    service = create_service()
    service.import_records(
        flow_date="2026-07-15",
        records=[record("BK1", "0.000000001万")],
    )

    with service._database.session() as session:
        stored = session.scalar(select(SectorFlowRecord))

    assert stored is not None
    assert str(stored.main_net_inflow_yuan) == "0.000010000"


def test_list_rejects_compact_non_canonical_flow_date() -> None:
    """Only the documented YYYY-MM-DD date form is accepted at the service boundary."""

    service = create_service()

    with pytest.raises(ValidationError, match="date must be in YYYY-MM-DD format"):
        service.list_records(
            flow_date="20260715",
            sector_code=None,
            direction=None,
            limit=None,
        )


def test_import_rejects_unrepresentable_yuan_precision_before_writing() -> None:
    """A parsed amount beyond the database scale fails without creating any rows."""

    service = create_service()

    with pytest.raises(ValidationError, match=r"main_net_inflow_yuan.*9 decimal places"):
        service.import_records(
            flow_date="2026-07-15",
            records=[record("BK1", "0.00000000000001万")],
        )

    result = service.list_records(
        flow_date="2026-07-15", sector_code=None, direction=None, limit=None
    )
    assert result["count"] == 0
