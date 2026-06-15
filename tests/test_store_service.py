"""Tests for the local multi-user portfolio store service."""

from __future__ import annotations

from decimal import Decimal

import pytest

from amstock.config import AppSettings
from amstock.exceptions import ValidationError
from amstock.services import create_application_context
from amstock.services.store import StoreService
from amstock.time import FixedClock


def create_service() -> StoreService:
    """Create a store service backed by an in-memory database."""

    context = create_application_context(AppSettings(database_url="sqlite+pysqlite:///:memory:"))
    context.database.create_schema()
    return StoreService(database=context.database, clock=FixedClock(1_800_000_000))


def test_store_calculates_fifo_realized_and_unrealized_pnl() -> None:
    """Sells reduce earliest lots and marks produce unrealized PnL."""

    service = create_service()
    service.create_user(username="alice", display_name="张三")
    service.record_trade(
        username="alice",
        action="buy",
        symbol="600519",
        name="贵州茅台",
        quantity=Decimal("100"),
        price=Decimal("10"),
        fee=Decimal("10"),
        trade_date="2026-01-01",
    )
    service.record_trade(
        username="alice",
        action="buy",
        symbol="600519",
        name="贵州茅台",
        quantity=Decimal("100"),
        price=Decimal("12"),
        trade_date="2026-01-02",
    )
    service.record_trade(
        username="alice",
        action="sell",
        symbol="600519",
        name=None,
        quantity=Decimal("50"),
        price=Decimal("15"),
        fee=Decimal("5"),
        trade_date="2026-01-03",
    )

    report = service.summary(username="alice", marks={"600519": Decimal("14")})

    position = report["positions"][0]
    assert position["name"] == "贵州茅台"
    assert position["quantity"] == "150.0000"
    assert position["cost"] == "1705.0000"
    assert position["avg_cost"] == "11.3667"
    assert position["realized_pnl"] == "240.0000"
    assert position["unrealized_pnl"] == "395.0000"
    assert report["totals"]["total_pnl"] == "635.0000"


def test_store_rejects_sell_that_exceeds_holdings() -> None:
    """A sell cannot create a negative position."""

    service = create_service()
    service.create_user(username="alice")
    service.record_trade(
        username="alice",
        action="buy",
        symbol="000001",
        name="平安银行",
        quantity=Decimal("100"),
        price=Decimal("10"),
        trade_date="2026-01-01",
    )

    with pytest.raises(ValidationError, match="sell quantity exceeds holdings"):
        service.record_trade(
            username="alice",
            action="sell",
            symbol="000001",
            name=None,
            quantity=Decimal("101"),
            price=Decimal("11"),
            trade_date="2026-01-02",
        )

    trades = service.list_trades(username="alice")
    assert trades["count"] == 1


def test_store_deletes_trade_and_recalculates_positions() -> None:
    """Deleting one transaction removes it from future calculations."""

    service = create_service()
    service.create_user(username="alice")
    first = service.record_trade(
        username="alice",
        action="buy",
        symbol="000001",
        name="平安银行",
        quantity=Decimal("100"),
        price=Decimal("10"),
        trade_date="2026-01-01",
    )
    service.record_trade(
        username="alice",
        action="buy",
        symbol="000001",
        name="平安银行",
        quantity=Decimal("50"),
        price=Decimal("12"),
        trade_date="2026-01-02",
    )

    deleted = service.delete_trade(
        username="alice",
        transaction_id=first["transaction"]["id"],
    )

    assert deleted["transaction"]["id"] == first["transaction"]["id"]
    trades = service.list_trades(username="alice")
    assert trades["count"] == 1
    position = service.positions(username="alice")["positions"][0]
    assert position["quantity"] == "50.0000"
    assert position["cost"] == "600.0000"


def test_store_rejects_delete_that_would_invalidate_later_sell() -> None:
    """Deleting earlier buys cannot leave later sells without inventory."""

    service = create_service()
    service.create_user(username="alice")
    buy = service.record_trade(
        username="alice",
        action="buy",
        symbol="000001",
        name="平安银行",
        quantity=Decimal("100"),
        price=Decimal("10"),
        trade_date="2026-01-01",
    )
    service.record_trade(
        username="alice",
        action="sell",
        symbol="000001",
        name=None,
        quantity=Decimal("50"),
        price=Decimal("11"),
        trade_date="2026-01-02",
    )

    with pytest.raises(ValidationError, match="sell quantity exceeds holdings"):
        service.delete_trade(
            username="alice",
            transaction_id=buy["transaction"]["id"],
        )

    assert service.list_trades(username="alice")["count"] == 2


def test_deactivated_user_cannot_record_new_trade() -> None:
    """Inactive users remain queryable but cannot receive new transactions."""

    service = create_service()
    service.create_user(username="alice")
    service.set_user_active(username="alice", is_active=False)

    with pytest.raises(ValidationError, match="user is inactive"):
        service.record_trade(
            username="alice",
            action="buy",
            symbol="000001",
            name=None,
            quantity=Decimal("100"),
            price=Decimal("10"),
            trade_date="2026-01-01",
        )

    assert service.summary(username="alice")["totals"]["open_cost"] == "0.0000"
