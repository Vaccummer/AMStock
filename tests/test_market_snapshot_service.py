"""Tests for dated full-market snapshot persistence and exact queries."""

from __future__ import annotations

from dataclasses import fields
from decimal import Decimal

import pytest
from sqlalchemy import inspect, select

from amstock.config import AppSettings
from amstock.exceptions import ValidationError
from amstock.market_snapshot_io import MarketSnapshotInput
from amstock.models.market_snapshot import MarketSnapshotRecord
from amstock.services import create_application_context
from amstock.services.market_snapshot import MarketSnapshotService
from amstock.time import FixedClock


def create_service() -> MarketSnapshotService:
    """Create a service backed by an isolated in-memory database."""

    context = create_application_context(AppSettings(database_url="sqlite+pysqlite:///:memory:"))
    context.database.create_schema()
    return MarketSnapshotService(database=context.database, clock=FixedClock(1_800_000_000))


def record(code: str, **changes: object) -> MarketSnapshotInput:
    """Build a complete parsed snapshot with deterministic nullable metrics."""

    values: dict[str, object] = {
        field.name: None for field in fields(MarketSnapshotInput)
    }
    values.update(stock_code=code, stock_name=f"Stock {code}", industry="Industry")
    values.update(changes)
    return MarketSnapshotInput(**values)  # type: ignore[arg-type]


def list_records(service: MarketSnapshotService, **changes: object) -> dict[str, object]:
    """Call the service with the documented query defaults."""

    arguments: dict[str, object] = {
        "snapshot_date": "2026-07-15",
        "code": None,
        "name": None,
        "industry": None,
        "min_change": None,
        "max_change": None,
        "min_turnover": None,
        "max_turnover": None,
        "min_pe": None,
        "max_pe": None,
        "min_market_cap": None,
        "max_market_cap": None,
        "sort_by": "stock_code",
        "order": "asc",
        "limit": 100,
    }
    arguments.update(changes)
    return service.list_records(**arguments)  # type: ignore[arg-type]


def test_schema_and_sqlite_round_trip_preserve_every_nullable_exact_decimal() -> None:
    service = create_service()
    numeric_names = [
        field.name
        for field in fields(MarketSnapshotInput)
        if field.name not in {"stock_code", "stock_name", "industry"}
    ]
    values = {name: Decimal("123456789.123456789") for name in numeric_names}
    values["latest"] = Decimal("1234567890123456789")
    service.import_records(snapshot_date="2026-07-15", records=[record("000001", **values)])

    assert "market_snapshot_records" in inspect(service._database.engine).get_table_names()
    with service._database.session() as session:
        stored = session.scalar(select(MarketSnapshotRecord))
    assert stored is not None
    assert stored.latest == Decimal("1234567890123456789")
    assert all(getattr(stored, name) == values[name] for name in numeric_names)
    with service._database.engine.connect() as connection:
        raw = connection.exec_driver_sql(
            "SELECT latest, change_percent, typeof(latest) FROM market_snapshot_records"
        ).one()
    assert raw == ("1234567890123456789", "123456789.123456789", "text")


def test_import_upserts_same_date_and_retains_absent_rows() -> None:
    service = create_service()
    first = service.import_records(
        snapshot_date="2026-07-15",
        records=[record("000001", latest=Decimal("1")), record("000002")],
    )
    second = service.import_records(
        snapshot_date="2026-07-15",
        records=[record("000001", latest=Decimal("2"))],
    )

    result = list_records(service)
    assert first == {
        "ok": True,
        "snapshot_date": "2026-07-15",
        "rows_read": 2,
        "inserted": 2,
        "updated": 0,
    }
    assert second == {
        "ok": True,
        "snapshot_date": "2026-07-15",
        "rows_read": 1,
        "inserted": 0,
        "updated": 1,
    }
    assert [item["stock_code"] for item in result["records"]] == ["000001", "000002"]
    assert result["records"][0]["latest"] == "2"


@pytest.mark.parametrize("value", ["20260715", "2026-7-15", "2026-02-30"])
def test_import_and_list_reject_noncanonical_or_invalid_dates(value: str) -> None:
    service = create_service()
    with pytest.raises(ValidationError, match="date must be in YYYY-MM-DD format"):
        service.import_records(snapshot_date=value, records=[record("000001")])
    with pytest.raises(ValidationError, match="date must be in YYYY-MM-DD format"):
        list_records(service, snapshot_date=value)


def test_empty_import_is_rejected_before_any_rows_are_written() -> None:
    service = create_service()
    with pytest.raises(ValidationError, match="market snapshot file contains no records"):
        service.import_records(snapshot_date="2026-07-15", records=[])
    assert list_records(service)["count"] == 0


def test_text_filters_use_exact_code_and_name_and_industry_contains() -> None:
    service = create_service()
    service.import_records(
        snapshot_date="2026-07-15",
        records=[
            record("000001", stock_name="Alpha Bank", industry="Finance Banking"),
            record("000010", stock_name="Beta Tech", industry="Software"),
        ],
    )

    assert list_records(service, code="000001")["count"] == 1
    assert list_records(service, code="00001")["count"] == 0
    assert list_records(service, name="Bank")["count"] == 1
    assert list_records(service, industry="Soft")["count"] == 1


@pytest.mark.parametrize(
    ("field", "minimum", "maximum"),
    (
        ("change_percent", "min_change", "max_change"),
        ("turnover_percent", "min_turnover", "max_turnover"),
        ("dynamic_pe", "min_pe", "max_pe"),
        ("total_market_cap_yuan", "min_market_cap", "max_market_cap"),
    ),
)
def test_each_numeric_range_family_uses_inclusive_exact_decimal_comparisons(
    field: str, minimum: str, maximum: str
) -> None:
    service = create_service()
    service.import_records(
        snapshot_date="2026-07-15",
        records=[
            record("000001", **{field: Decimal("2.000000000000000001")}),
            record("000002", **{field: Decimal("10")}),
            record("000003", **{field: None}),
        ],
    )

    result = list_records(
        service,
        **{
            minimum: Decimal("2.000000000000000001"),
            maximum: Decimal("9.999999999999999999"),
        },
    )
    assert [item["stock_code"] for item in result["records"]] == ["000001"]


@pytest.mark.parametrize("order", ["asc", "desc"])
def test_whitelisted_sorting_is_numeric_and_uses_code_tie_break(order: str) -> None:
    service = create_service()
    service.import_records(
        snapshot_date="2026-07-15",
        records=[
            record("000002", change_percent=Decimal("2")),
            record("000001", change_percent=Decimal("2")),
            record("000003", change_percent=Decimal("10")),
            record("000004", change_percent=None),
        ],
    )

    result = list_records(service, sort_by="change_percent", order=order)
    expected = ["000004", "000001", "000002", "000003"]
    if order == "desc":
        expected = ["000003", "000001", "000002", "000004"]
    assert [item["stock_code"] for item in result["records"]] == expected


def test_default_limit_is_100_and_invalid_query_options_are_rejected() -> None:
    service = create_service()
    service.import_records(
        snapshot_date="2026-07-15",
        records=[record(f"{index:06d}") for index in range(101)],
    )
    assert list_records(service)["count"] == 100

    for changes, message in (
        ({"sort_by": "unknown"}, "invalid sort_by"),
        ({"order": "sideways"}, "order must be asc or desc"),
        ({"limit": 0}, "limit must be positive"),
        ({"limit": -1}, "limit must be positive"),
    ):
        with pytest.raises(ValidationError, match=message):
            list_records(service, **changes)


def test_payload_returns_all_fields_and_display_values_for_scaled_columns() -> None:
    service = create_service()
    service.import_records(
        snapshot_date="2026-07-15",
        records=[
            record(
                "000001",
                amount_yuan=Decimal("123000000"),
                total_shares=Decimal("250000000"),
                total_volume=Decimal("12000"),
            )
        ],
    )

    [payload] = list_records(service)["records"]
    assert set(field.name for field in fields(MarketSnapshotInput)) <= payload.keys()
    assert payload["amount_yuan"] == "123000000"
    assert payload["amount_display"] == "1.23亿"
    assert payload["total_shares_display"] == "2.5亿"
    assert payload["total_volume_display"] == "1.2万"
    assert payload["ask_price"] is None
