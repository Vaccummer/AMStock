"""Application service for the local multi-user portfolio store."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Literal, cast

from amstock.exceptions import NotFoundError, ValidationError
from amstock.models.store import StoreTransaction, StoreUser
from amstock.repositories.store import StoreRepository

if TYPE_CHECKING:
    from amstock.db.engine import Database
    from amstock.time import Clock

StoreAction = Literal["buy", "sell", "import"]

MONEY_QUANT = Decimal("0.0001")
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(slots=True)
class Lot:
    """Open holding lot used for FIFO cost accounting."""

    quantity: Decimal
    unit_cost: Decimal


class StoreService:
    """Coordinates local store operations."""

    def __init__(self, *, database: Database, clock: Clock) -> None:
        self._database = database
        self._clock = clock

    def create_user(self, *, username: str, display_name: str | None = None) -> dict[str, object]:
        """Create a local ledger user."""

        normalized_username = normalize_username(username)
        now = self._clock.now_epoch()
        with self._database.session() as session:
            repository = StoreRepository(session)
            existing = repository.get_user_by_username(normalized_username)
            if existing is not None:
                msg = f"user already exists: {normalized_username}"
                raise ValidationError(msg)
            user = repository.add_user(
                StoreUser(
                    username=normalized_username,
                    display_name=clean_optional_text(display_name),
                    is_active=True,
                    created_at=now,
                    updated_at=None,
                )
            )
            session.commit()
            return {"ok": True, "user": user_payload(user)}

    def list_users(self, *, include_inactive: bool = False) -> dict[str, object]:
        """Return local ledger users."""

        with self._database.session() as session:
            users = StoreRepository(session).list_users(include_inactive=include_inactive)
            return {
                "ok": True,
                "count": len(users),
                "users": [user_payload(user) for user in users],
            }

    def rename_user(self, *, username: str, display_name: str | None) -> dict[str, object]:
        """Update a user's display name."""

        now = self._clock.now_epoch()
        with self._database.session() as session:
            user = self._get_user(StoreRepository(session), username)
            user.display_name = clean_optional_text(display_name)
            user.updated_at = now
            session.commit()
            return {"ok": True, "user": user_payload(user)}

    def set_user_active(self, *, username: str, is_active: bool) -> dict[str, object]:
        """Activate or deactivate a user."""

        now = self._clock.now_epoch()
        with self._database.session() as session:
            user = self._get_user(StoreRepository(session), username)
            user.is_active = is_active
            user.updated_at = now
            session.commit()
            return {"ok": True, "user": user_payload(user)}

    def record_trade(
        self,
        *,
        username: str,
        action: StoreAction,
        symbol: str,
        name: str | None,
        quantity: Decimal,
        price: Decimal,
        fee: Decimal = Decimal("0"),
        tax: Decimal = Decimal("0"),
        trade_date: str | None = None,
        note: str | None = None,
    ) -> dict[str, object]:
        """Record a buy, sell, or imported opening position."""

        normalized_action = validate_action(action)
        normalized_symbol = normalize_symbol(symbol)
        normalized_date = validate_trade_date(trade_date)
        now = self._clock.now_epoch()

        with self._database.session() as session:
            repository = StoreRepository(session)
            user = self._get_user(repository, username, require_active=True)
            transaction = repository.add_transaction(
                StoreTransaction(
                    user_id=user.id,
                    symbol=normalized_symbol,
                    name=clean_optional_text(name),
                    action=normalized_action,
                    quantity=positive_decimal(quantity, "quantity"),
                    price=positive_decimal(price, "price"),
                    fee=non_negative_decimal(fee, "fee"),
                    tax=non_negative_decimal(tax, "tax"),
                    trade_date=normalized_date,
                    note=clean_optional_text(note),
                    created_at=now,
                    updated_at=None,
                )
            )
            calculate_portfolio(repository.list_transactions(user_id=user.id))
            session.commit()
            return {"ok": True, "transaction": transaction_payload(transaction)}

    def list_trades(
        self,
        *,
        username: str,
        symbol: str | None = None,
        limit: int | None = None,
    ) -> dict[str, object]:
        """Return a user's recorded transactions."""

        normalized_symbol = normalize_symbol(symbol) if symbol is not None else None
        if limit is not None and limit <= 0:
            raise ValidationError("limit must be positive")
        with self._database.session() as session:
            repository = StoreRepository(session)
            user = self._get_user(repository, username)
            transactions = repository.list_transactions(user_id=user.id, symbol=normalized_symbol)
            if limit is not None:
                transactions = transactions[-limit:]
            return {
                "ok": True,
                "count": len(transactions),
                "transactions": [transaction_payload(item) for item in transactions],
            }

    def delete_trade(self, *, username: str, transaction_id: int) -> dict[str, object]:
        """Delete one recorded transaction."""

        if transaction_id <= 0:
            raise ValidationError("transaction id must be positive")
        with self._database.session() as session:
            repository = StoreRepository(session)
            user = self._get_user(repository, username)
            transaction = repository.get_transaction(
                user_id=user.id,
                transaction_id=transaction_id,
            )
            if transaction is None:
                msg = f"transaction not found: {transaction_id}"
                raise NotFoundError(msg)
            deleted = transaction_payload(transaction)
            repository.delete_transaction(transaction)
            calculate_portfolio(repository.list_transactions(user_id=user.id))
            session.commit()
            return {"ok": True, "transaction": deleted}

    def positions(
        self,
        *,
        username: str,
        marks: dict[str, Decimal] | None = None,
    ) -> dict[str, object]:
        """Return current positions for a user."""

        with self._database.session() as session:
            repository = StoreRepository(session)
            user = self._get_user(repository, username)
            report = calculate_portfolio(repository.list_transactions(user_id=user.id), marks)
            return {"ok": True, "positions": report["positions"]}

    def summary(
        self,
        *,
        username: str,
        marks: dict[str, Decimal] | None = None,
    ) -> dict[str, object]:
        """Return current positions and portfolio totals for a user."""

        with self._database.session() as session:
            repository = StoreRepository(session)
            user = self._get_user(repository, username)
            report = calculate_portfolio(repository.list_transactions(user_id=user.id), marks)
            return {"ok": True, **report}

    def _get_user(
        self,
        repository: StoreRepository,
        username: str,
        *,
        require_active: bool = False,
    ) -> StoreUser:
        normalized_username = normalize_username(username)
        user = repository.get_user_by_username(normalized_username)
        if user is None:
            msg = f"user not found: {normalized_username}"
            raise NotFoundError(msg)
        if require_active and not user.is_active:
            msg = f"user is inactive: {normalized_username}"
            raise ValidationError(msg)
        return user


def calculate_portfolio(
    transactions: list[StoreTransaction],
    marks: dict[str, Decimal] | None = None,
) -> dict[str, object]:
    """Calculate holdings, cost basis, realized PnL, and marked returns."""

    normalized_marks = {normalize_symbol(symbol): price for symbol, price in (marks or {}).items()}
    lots_by_symbol: dict[str, list[Lot]] = {}
    meta_by_symbol: dict[str, dict[str, str | None]] = {}
    realized_by_symbol: dict[str, Decimal] = {}

    for transaction in sorted(transactions, key=lambda item: (item.trade_date, item.id)):
        lots = lots_by_symbol.setdefault(transaction.symbol, [])
        current_meta = meta_by_symbol.setdefault(
            transaction.symbol,
            {"symbol": transaction.symbol, "name": transaction.name},
        )
        if transaction.name:
            current_meta["name"] = transaction.name

        if transaction.action in {"buy", "import"}:
            lots.append(
                Lot(
                    quantity=transaction.quantity,
                    unit_cost=(
                        transaction.quantity * transaction.price
                        + transaction.fee
                        + transaction.tax
                    )
                    / transaction.quantity,
                )
            )
            continue

        if transaction.action != "sell":
            msg = f"unsupported transaction action: {transaction.action}"
            raise ValidationError(msg)

        remaining = transaction.quantity
        closing_costs = transaction.fee + transaction.tax
        realized = Decimal("0")

        while remaining > 0:
            if not lots:
                msg = f"sell quantity exceeds holdings for {transaction.symbol}"
                raise ValidationError(msg)
            lot = lots[0]
            used = min(remaining, lot.quantity)
            proportional_costs = closing_costs * (used / transaction.quantity)
            realized += used * transaction.price - proportional_costs - used * lot.unit_cost
            lot.quantity -= used
            remaining -= used
            if lot.quantity == 0:
                lots.pop(0)

        realized_by_symbol[transaction.symbol] = realized_by_symbol.get(
            transaction.symbol,
            Decimal("0"),
        ) + realized

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
        mark_price = normalized_marks.get(symbol)
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
            "marked_market_value": money(total_market_value) if normalized_marks else None,
            "realized_pnl": money(total_realized),
            "unrealized_pnl": money(total_unrealized) if normalized_marks else None,
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
            raise ValidationError(msg)
        try:
            mark_price = Decimal(price)
        except Exception as exc:
            raise ValidationError("mark price must be a decimal number") from exc
        marks[normalize_symbol(symbol)] = positive_decimal(mark_price, "mark price")
    return marks


def validate_action(action: str) -> StoreAction:
    """Validate and normalize a transaction action."""

    if action not in {"buy", "sell", "import"}:
        msg = f"unsupported transaction action: {action}"
        raise ValidationError(msg)
    return cast("StoreAction", action)


def normalize_username(username: str) -> str:
    """Normalize a local ledger username."""

    normalized = username.strip().lower()
    if not normalized:
        raise ValidationError("username is required")
    if USERNAME_PATTERN.fullmatch(normalized) is None:
        raise ValidationError(
            "username may contain only letters, numbers, dot, underscore, or dash"
        )
    return normalized


def normalize_symbol(symbol: str) -> str:
    """Normalize stock symbols for ledger keys."""

    normalized = symbol.strip().lower()
    if not normalized:
        raise ValidationError("symbol is required")
    return normalized.replace("sh.", "sh").replace("sz.", "sz").replace("bj.", "bj")


def validate_trade_date(value: str | None) -> str:
    """Validate a YYYY-MM-DD trade date."""

    if value is None:
        return date.today().isoformat()
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValidationError("date must be in YYYY-MM-DD format") from exc


def positive_decimal(value: Decimal, field: str) -> Decimal:
    """Validate a positive decimal."""

    if value <= 0:
        msg = f"{field} must be positive"
        raise ValidationError(msg)
    return value


def non_negative_decimal(value: Decimal, field: str) -> Decimal:
    """Validate a non-negative decimal."""

    if value < 0:
        msg = f"{field} must be non-negative"
        raise ValidationError(msg)
    return value


def clean_optional_text(value: str | None) -> str | None:
    """Normalize optional CLI text fields."""

    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def money(value: Decimal | None) -> str | None:
    """Serialize a decimal with stable precision."""

    if value is None:
        return None
    return str(value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP))


def user_payload(user: StoreUser) -> dict[str, object]:
    """Serialize a store user."""

    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "is_active": user.is_active,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
    }


def transaction_payload(transaction: StoreTransaction) -> dict[str, object]:
    """Serialize a store transaction."""

    return {
        "id": transaction.id,
        "user_id": transaction.user_id,
        "symbol": transaction.symbol,
        "name": transaction.name,
        "action": transaction.action,
        "quantity": money(transaction.quantity),
        "price": money(transaction.price),
        "fee": money(transaction.fee),
        "tax": money(transaction.tax),
        "trade_date": transaction.trade_date,
        "note": transaction.note,
        "created_at": transaction.created_at,
        "updated_at": transaction.updated_at,
    }
