"""Record stock transactions and calculate portfolio returns."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Literal

Action = Literal["buy", "sell"]

SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STORE_PATH = SKILL_ROOT / "data" / "portfolio.json"
MONEY_QUANT = Decimal("0.0001")


@dataclass(frozen=True, slots=True)
class Trade:
    """One portfolio transaction."""

    id: int
    date: str
    symbol: str
    name: str | None
    action: Action
    quantity: Decimal
    price: Decimal
    fee: Decimal
    note: str | None


@dataclass(slots=True)
class Lot:
    """Open holding lot used for FIFO cost accounting."""

    quantity: Decimal
    unit_cost: Decimal


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--store",
        type=Path,
        default=DEFAULT_STORE_PATH,
        help="Portfolio JSON store path.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    record = subparsers.add_parser("record", help="Record a buy or sell transaction.")
    record.add_argument("action", choices=["buy", "sell"], help="Transaction action.")
    record.add_argument("--symbol", required=True, help="Stock symbol, e.g. 600519 or sz.000001.")
    record.add_argument("--name", help="Optional stock name.")
    record.add_argument("--quantity", required=True, type=Decimal, help="Share quantity.")
    record.add_argument("--price", required=True, type=Decimal, help="Transaction price per share.")
    record.add_argument("--fee", default=Decimal("0"), type=Decimal, help="Total transaction fee.")
    record.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="Trade date in YYYY-MM-DD.",
    )
    record.add_argument("--note", help="Optional note.")

    trades = subparsers.add_parser("trades", help="List recorded transactions.")
    trades.add_argument("--symbol", help="Filter by symbol.")
    trades.add_argument("--limit", type=int, help="Maximum trades to return.")

    positions = subparsers.add_parser("positions", help="Calculate current holdings.")
    positions.add_argument(
        "--mark",
        action="append",
        default=[],
        help="Mark price as SYMBOL=PRICE. Can be repeated.",
    )

    summary = subparsers.add_parser("summary", help="Calculate portfolio return summary.")
    summary.add_argument(
        "--mark",
        action="append",
        default=[],
        help="Mark price as SYMBOL=PRICE. Can be repeated.",
    )

    subparsers.add_parser("reset", help="Clear the portfolio store.")
    return parser


def load_trades(store: Path) -> list[Trade]:
    """Load trades from the JSON store."""

    if not store.exists():
        return []

    payload = json.loads(store.read_text(encoding="utf-8"))
    return [_trade_from_payload(item) for item in payload.get("trades", [])]


def save_trades(store: Path, trades: list[Trade]) -> None:
    """Save trades to the JSON store."""

    store.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "trades": [_trade_to_payload(trade) for trade in trades],
    }
    store.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def next_trade_id(trades: list[Trade]) -> int:
    """Return the next transaction id."""

    if not trades:
        return 1
    return max(trade.id for trade in trades) + 1


def record_trade(args: argparse.Namespace) -> dict[str, object]:
    """Record a transaction and return it."""

    trades = load_trades(args.store)
    trade = Trade(
        id=next_trade_id(trades),
        date=args.date,
        symbol=normalize_symbol(args.symbol),
        name=args.name,
        action=args.action,
        quantity=positive_decimal(args.quantity, "quantity"),
        price=positive_decimal(args.price, "price"),
        fee=non_negative_decimal(args.fee, "fee"),
        note=args.note,
    )
    trades.append(trade)
    save_trades(args.store, trades)
    return {"ok": True, "trade": _trade_to_payload(trade), "store": str(args.store)}


def list_trades(args: argparse.Namespace) -> dict[str, object]:
    """Return recorded transactions."""

    symbol = normalize_symbol(args.symbol) if args.symbol else None
    trades = load_trades(args.store)
    if symbol:
        trades = [trade for trade in trades if trade.symbol == symbol]
    if args.limit is not None:
        trades = trades[-args.limit :]
    return {
        "ok": True,
        "count": len(trades),
        "trades": [_trade_to_payload(trade) for trade in trades],
        "store": str(args.store),
    }


def positions_payload(args: argparse.Namespace) -> dict[str, object]:
    """Return current position data."""

    marks = parse_marks(args.mark)
    report = calculate_portfolio(load_trades(args.store), marks)
    return {"ok": True, "positions": report["positions"], "store": str(args.store)}


def summary_payload(args: argparse.Namespace) -> dict[str, object]:
    """Return portfolio return summary."""

    marks = parse_marks(args.mark)
    report = calculate_portfolio(load_trades(args.store), marks)
    return {"ok": True, **report, "store": str(args.store)}


def reset_store(args: argparse.Namespace) -> dict[str, object]:
    """Clear the portfolio store."""

    save_trades(args.store, [])
    return {"ok": True, "store": str(args.store), "trades": []}


def calculate_portfolio(
    trades: list[Trade],
    marks: dict[str, Decimal] | None = None,
) -> dict[str, object]:
    """Calculate holdings, cost basis, realized PnL, and marked returns."""

    marks = marks or {}
    lots_by_symbol: dict[str, list[Lot]] = {}
    meta_by_symbol: dict[str, dict[str, str | None]] = {}
    realized_by_symbol: dict[str, Decimal] = {}
    proceeds_by_symbol: dict[str, Decimal] = {}

    for trade in sorted(trades, key=lambda item: (item.date, item.id)):
        lots = lots_by_symbol.setdefault(trade.symbol, [])
        current_meta = meta_by_symbol.setdefault(
            trade.symbol,
            {"symbol": trade.symbol, "name": trade.name},
        )
        if trade.name:
            current_meta["name"] = trade.name

        if trade.action == "buy":
            lots.append(
                Lot(
                    quantity=trade.quantity,
                    unit_cost=(trade.quantity * trade.price + trade.fee) / trade.quantity,
                )
            )
            continue

        remaining = trade.quantity
        sale_proceeds = trade.quantity * trade.price - trade.fee
        proceeds_by_symbol[trade.symbol] = proceeds_by_symbol.get(trade.symbol, Decimal("0"))
        proceeds_by_symbol[trade.symbol] += sale_proceeds
        realized = Decimal("0")

        while remaining > 0:
            if not lots:
                msg = f"sell quantity exceeds holdings for {trade.symbol}"
                raise ValueError(msg)
            lot = lots[0]
            used = min(remaining, lot.quantity)
            proportional_fee = trade.fee * (used / trade.quantity)
            realized += used * trade.price - proportional_fee - used * lot.unit_cost
            lot.quantity -= used
            remaining -= used
            if lot.quantity == 0:
                lots.pop(0)

        realized_by_symbol[trade.symbol] = realized_by_symbol.get(trade.symbol, Decimal("0"))
        realized_by_symbol[trade.symbol] += realized

    positions = []
    total_cost = Decimal("0")
    total_market_value = Decimal("0")
    total_unrealized = Decimal("0")
    total_realized = sum(realized_by_symbol.values(), Decimal("0"))

    for symbol in sorted(set(lots_by_symbol) | set(realized_by_symbol)):
        lots = lots_by_symbol.get(symbol, [])
        quantity = sum((lot.quantity for lot in lots), Decimal("0"))
        cost = sum((lot.quantity * lot.unit_cost for lot in lots), Decimal("0"))
        avg_cost = cost / quantity if quantity else Decimal("0")
        mark_price = marks.get(symbol)
        market_value = quantity * mark_price if mark_price is not None else None
        unrealized = market_value - cost if market_value is not None else None

        total_cost += cost
        if market_value is not None:
            total_market_value += market_value
        if unrealized is not None:
            total_unrealized += unrealized

        positions.append(
            {
                **meta_by_symbol.get(symbol, {"symbol": symbol, "name": None}),
                "quantity": money(quantity),
                "cost": money(cost),
                "avg_cost": money(avg_cost),
                "realized_pnl": money(realized_by_symbol.get(symbol, Decimal("0"))),
                "mark_price": money(mark_price) if mark_price is not None else None,
                "market_value": money(market_value) if market_value is not None else None,
                "unrealized_pnl": money(unrealized) if unrealized is not None else None,
                "total_pnl": money(
                    realized_by_symbol.get(symbol, Decimal("0")) + (unrealized or Decimal("0"))
                ),
            }
        )

    total_pnl = total_realized + total_unrealized
    return {
        "positions": positions,
        "totals": {
            "open_cost": money(total_cost),
            "marked_market_value": money(total_market_value) if marks else None,
            "realized_pnl": money(total_realized),
            "unrealized_pnl": money(total_unrealized) if marks else None,
            "total_pnl": money(total_pnl),
        },
    }


def parse_marks(values: list[str]) -> dict[str, Decimal]:
    """Parse repeated SYMBOL=PRICE mark arguments."""

    marks: dict[str, Decimal] = {}
    for value in values:
        symbol, separator, price = value.partition("=")
        if not separator:
            msg = f"invalid mark {value!r}; expected SYMBOL=PRICE"
            raise ValueError(msg)
        marks[normalize_symbol(symbol)] = positive_decimal(Decimal(price), "mark price")
    return marks


def normalize_symbol(symbol: str) -> str:
    """Normalize stock symbols for ledger keys."""

    return symbol.strip().lower().replace("sh.", "sh").replace("sz.", "sz").replace("bj.", "bj")


def positive_decimal(value: Decimal, field: str) -> Decimal:
    """Validate a positive decimal."""

    if value <= 0:
        msg = f"{field} must be positive"
        raise ValueError(msg)
    return value


def non_negative_decimal(value: Decimal, field: str) -> Decimal:
    """Validate a non-negative decimal."""

    if value < 0:
        msg = f"{field} must be non-negative"
        raise ValueError(msg)
    return value


def money(value: Decimal | None) -> str | None:
    """Serialize a decimal with stable precision."""

    if value is None:
        return None
    return str(value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP))


def _trade_to_payload(trade: Trade) -> dict[str, object]:
    return {
        **asdict(trade),
        "quantity": money(trade.quantity),
        "price": money(trade.price),
        "fee": money(trade.fee),
    }


def _trade_from_payload(payload: dict[str, Any]) -> Trade:
    return Trade(
        id=int(payload["id"]),
        date=str(payload["date"]),
        symbol=str(payload["symbol"]),
        name=payload.get("name"),
        action=payload["action"],
        quantity=Decimal(str(payload["quantity"])),
        price=Decimal(str(payload["price"])),
        fee=Decimal(str(payload.get("fee", "0"))),
        note=payload.get("note"),
    )


def emit_json(payload: dict[str, object]) -> None:
    """Print a JSON payload."""

    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def main() -> None:
    """Run the command-line application."""

    args = build_parser().parse_args()
    try:
        handlers = {
            "record": record_trade,
            "trades": list_trades,
            "positions": positions_payload,
            "summary": summary_payload,
            "reset": reset_store,
        }
        emit_json(handlers[args.command](args))
    except Exception as exc:
        emit_json({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}})
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
