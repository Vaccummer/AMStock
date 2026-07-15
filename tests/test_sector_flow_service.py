"""Tests for dated sector-flow persistence and queries."""

from __future__ import annotations

from dataclasses import replace
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
    first_import = service.import_records(
        flow_date="2026-07-15",
        records=[record("BK1", "10万"), record("BK2", "-2亿")],
    )
    second_import = service.import_records(
        flow_date="2026-07-15", records=[record("BK1", "-2355万")]
    )

    result = service.list_records(
        flow_date="2026-07-15", sector_code=None, direction="out", limit=None
    )

    assert result["count"] == 2
    assert [item["sector_code"] for item in result["records"]] == ["BK2", "BK1"]
    assert result["records"][1]["main_net_inflow_yuan"] == "-23550000"
    assert result["records"][0]["main_net_inflow_display"] == "-2亿"
    assert first_import == {
        "ok": True,
        "flow_date": "2026-07-15",
        "rows_read": 2,
        "inserted": 2,
        "updated": 0,
    }
    assert second_import == {
        "ok": True,
        "flow_date": "2026-07-15",
        "rows_read": 1,
        "inserted": 0,
        "updated": 1,
    }


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
    assert stored.main_net_inflow_yuan == Decimal("0.00001")


def test_sqlite_round_trip_preserves_large_and_fractional_decimals_exactly() -> None:
    """Every Decimal column uses lossless text rather than SQLite numeric affinity."""

    service = create_service()
    snapshot = replace(
        record("BK1", "1万"),
        latest=Decimal("1234567890123456789"),
        change_percent=Decimal("123456789.123456789"),
        auction_yuan=Decimal("1.2300"),
    )
    service.import_records(flow_date="2026-07-15", records=[snapshot])

    with service._database.session() as session:
        stored = session.scalar(select(SectorFlowRecord))

    assert stored is not None
    assert stored.latest == Decimal("1234567890123456789")
    assert stored.change_percent == Decimal("123456789.123456789")
    with service._database.engine.connect() as connection:
        raw = connection.exec_driver_sql(
            "SELECT latest, change_percent, auction_yuan, typeof(latest) "
            "FROM sector_flow_records"
        ).one()
    assert raw == (
        "1234567890123456789",
        "123456789.123456789",
        "1.23",
        "text",
    )


def test_list_orders_filters_and_limits_exact_decimals_in_python() -> None:
    """Text-backed exact values retain numeric query semantics."""

    service = create_service()
    snapshots = [
        replace(record("BK_POS", "1万"), main_net_inflow_yuan=Decimal("1234567890123456789")),
        replace(record("BK_OUT_2", "-1万"), main_net_inflow_yuan=Decimal("-123456789.123456789")),
        replace(record("BK_ZERO", "0万"), main_net_inflow_yuan=Decimal("0")),
        replace(record("BK_OUT_1", "-2万"), main_net_inflow_yuan=Decimal("-1234567890123456789")),
    ]
    service.import_records(flow_date="2026-07-15", records=snapshots)

    result = service.list_records(
        flow_date="2026-07-15", sector_code=None, direction="out", limit=1
    )

    assert result["count"] == 1
    assert [item["sector_code"] for item in result["records"]] == ["BK_OUT_1"]


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
