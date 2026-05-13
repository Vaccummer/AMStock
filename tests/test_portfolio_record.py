"""Tests for local portfolio record calculations."""

from __future__ import annotations

import importlib.util
import sys
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "skills/amstock-portfolio-record/scripts/portfolio_record.py"


def load_portfolio_module() -> object:
    """Load the portfolio script as a module for focused tests."""

    spec = importlib.util.spec_from_file_location("portfolio_record", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        msg = "could not load portfolio_record.py"
        raise RuntimeError(msg)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_calculate_fifo_realized_and_unrealized_pnl() -> None:
    """Sells reduce the earliest lot and marks produce unrealized PnL."""

    portfolio_record = load_portfolio_module()
    trades = [
        portfolio_record.Trade(
            id=1,
            date="2026-01-01",
            symbol="600519",
            name="贵州茅台",
            action="buy",
            quantity=Decimal("100"),
            price=Decimal("10"),
            fee=Decimal("10"),
            note=None,
        ),
        portfolio_record.Trade(
            id=2,
            date="2026-01-02",
            symbol="600519",
            name="贵州茅台",
            action="buy",
            quantity=Decimal("100"),
            price=Decimal("12"),
            fee=Decimal("0"),
            note=None,
        ),
        portfolio_record.Trade(
            id=3,
            date="2026-01-03",
            symbol="600519",
            name="贵州茅台",
            action="sell",
            quantity=Decimal("50"),
            price=Decimal("15"),
            fee=Decimal("5"),
            note="减仓",
        ),
    ]

    report = portfolio_record.calculate_portfolio(trades, {"600519": Decimal("14")})

    position = report["positions"][0]
    assert position["name"] == "贵州茅台"
    assert position["quantity"] == "150.0000"
    assert position["cost"] == "1705.0000"
    assert position["avg_cost"] == "11.3667"
    assert position["realized_pnl"] == "240.0000"
    assert position["unrealized_pnl"] == "395.0000"
    assert report["totals"]["total_pnl"] == "635.0000"


def test_save_and_load_trades_round_trip(tmp_path: Path) -> None:
    """The JSON ledger persists trades without losing decimal precision."""

    portfolio_record = load_portfolio_module()
    store = tmp_path / "portfolio.json"
    trades = [
        portfolio_record.Trade(
            id=1,
            date="2026-01-01",
            symbol="000001",
            name="平安银行",
            action="buy",
            quantity=Decimal("100.5"),
            price=Decimal("11.23"),
            fee=Decimal("1.23"),
            note=None,
        )
    ]

    portfolio_record.save_trades(store, trades)
    loaded = portfolio_record.load_trades(store)

    assert loaded == trades
