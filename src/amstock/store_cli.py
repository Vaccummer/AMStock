"""Local multi-user portfolio store CLI."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import TYPE_CHECKING, Annotated

import typer

from amstock.exceptions import AMStockError, ValidationError
from amstock.services import create_application_context
from amstock.services.store import StoreService, parse_marks

if TYPE_CHECKING:
    from collections.abc import Callable

app = typer.Typer(no_args_is_help=True)
admin_app = typer.Typer(no_args_is_help=True)
admin_user_app = typer.Typer(no_args_is_help=True)
trade_app = typer.Typer(no_args_is_help=True)

AdminTokenOption = Annotated[str, typer.Option("--admin-token", help="Configured admin token.")]
UsernameOption = Annotated[str, typer.Option("--user", help="Local ledger username.")]
SymbolOption = Annotated[str, typer.Option("--symbol", help="Stock symbol, e.g. 600519.")]
NameOption = Annotated[str | None, typer.Option("--name", help="Optional stock name.")]
QuantityOption = Annotated[str, typer.Option("--quantity", help="Share quantity.")]
PriceOption = Annotated[str, typer.Option("--price", help="Transaction price per share.")]
FeeOption = Annotated[str, typer.Option("--fee", help="Total transaction fee.")]
TaxOption = Annotated[str, typer.Option("--tax", help="Total transaction tax.")]
DateOption = Annotated[str | None, typer.Option("--date", help="Trade date in YYYY-MM-DD.")]
NoteOption = Annotated[str | None, typer.Option("--note", help="Optional note.")]
TransactionIdOption = Annotated[int, typer.Option("--id", help="Transaction id.")]
MarkOption = Annotated[
    list[str] | None,
    typer.Option("--mark", help="Mark price as SYMBOL=PRICE. Can be repeated."),
]


@admin_user_app.command("create")
def create_user(
    username: Annotated[str, typer.Option("--username", help="Local ledger username.")],
    admin_token: AdminTokenOption,
    display_name: Annotated[
        str | None,
        typer.Option("--display-name", help="Optional display name."),
    ] = None,
) -> None:
    """Create a local ledger user."""

    _run_json(
        lambda: _admin_store_service(admin_token).create_user(
            username=username,
            display_name=display_name,
        )
    )


@admin_user_app.command("list")
def list_users(
    admin_token: AdminTokenOption,
    include_inactive: Annotated[
        bool,
        typer.Option("--include-inactive", help="Include inactive users."),
    ] = False,
) -> None:
    """List local ledger users."""

    _run_json(
        lambda: _admin_store_service(admin_token).list_users(
            include_inactive=include_inactive,
        )
    )


@admin_user_app.command("rename")
def rename_user(
    username: Annotated[str, typer.Option("--username", help="Local ledger username.")],
    admin_token: AdminTokenOption,
    display_name: Annotated[
        str | None,
        typer.Option("--display-name", help="New display name. Empty clears it."),
    ] = None,
) -> None:
    """Rename a user's display name."""

    _run_json(
        lambda: _admin_store_service(admin_token).rename_user(
            username=username,
            display_name=display_name,
        )
    )


@admin_user_app.command("deactivate")
def deactivate_user(
    username: Annotated[str, typer.Option("--username", help="Local ledger username.")],
    admin_token: AdminTokenOption,
) -> None:
    """Deactivate a local ledger user."""

    _run_json(
        lambda: _admin_store_service(admin_token).set_user_active(
            username=username,
            is_active=False,
        )
    )


@admin_user_app.command("activate")
def activate_user(
    username: Annotated[str, typer.Option("--username", help="Local ledger username.")],
    admin_token: AdminTokenOption,
) -> None:
    """Activate a local ledger user."""

    _run_json(
        lambda: _admin_store_service(admin_token).set_user_active(
            username=username,
            is_active=True,
        )
    )


@trade_app.command("buy")
def buy(
    user: UsernameOption,
    symbol: SymbolOption,
    quantity: QuantityOption,
    price: PriceOption,
    name: NameOption = None,
    fee: FeeOption = "0",
    tax: TaxOption = "0",
    trade_date: DateOption = None,
    note: NoteOption = None,
) -> None:
    """Record a buy transaction."""

    _run_json(
        lambda: _store_service().record_trade(
            username=user,
            action="buy",
            symbol=symbol,
            name=name,
            quantity=parse_decimal(quantity, "quantity"),
            price=parse_decimal(price, "price"),
            fee=parse_decimal(fee, "fee"),
            tax=parse_decimal(tax, "tax"),
            trade_date=trade_date,
            note=note,
        )
    )


@trade_app.command("sell")
def sell(
    user: UsernameOption,
    symbol: SymbolOption,
    quantity: QuantityOption,
    price: PriceOption,
    name: NameOption = None,
    fee: FeeOption = "0",
    tax: TaxOption = "0",
    trade_date: DateOption = None,
    note: NoteOption = None,
) -> None:
    """Record a sell transaction."""

    _run_json(
        lambda: _store_service().record_trade(
            username=user,
            action="sell",
            symbol=symbol,
            name=name,
            quantity=parse_decimal(quantity, "quantity"),
            price=parse_decimal(price, "price"),
            fee=parse_decimal(fee, "fee"),
            tax=parse_decimal(tax, "tax"),
            trade_date=trade_date,
            note=note,
        )
    )


@trade_app.command("import-position")
def import_position(
    user: UsernameOption,
    symbol: SymbolOption,
    quantity: QuantityOption,
    avg_cost: Annotated[
        str,
        typer.Option("--avg-cost", help="Opening average cost per share."),
    ],
    name: NameOption = None,
    trade_date: DateOption = None,
    note: NoteOption = None,
) -> None:
    """Import an opening position as a ledger entry."""

    _run_json(
        lambda: _store_service().record_trade(
            username=user,
            action="import",
            symbol=symbol,
            name=name,
            quantity=parse_decimal(quantity, "quantity"),
            price=parse_decimal(avg_cost, "avg-cost"),
            fee=Decimal("0"),
            tax=Decimal("0"),
            trade_date=trade_date,
            note=note,
        )
    )


@trade_app.command("delete")
def delete_trade(
    user: UsernameOption,
    transaction_id: TransactionIdOption,
) -> None:
    """Delete one recorded transaction."""

    _run_json(
        lambda: _store_service().delete_trade(
            username=user,
            transaction_id=transaction_id,
        )
    )


@app.command("trades")
def trades(
    user: UsernameOption,
    symbol: Annotated[str | None, typer.Option("--symbol", help="Filter by symbol.")] = None,
    limit: Annotated[int | None, typer.Option("--limit", help="Maximum rows to return.")] = None,
) -> None:
    """List recorded transactions."""

    _run_json(lambda: _store_service().list_trades(username=user, symbol=symbol, limit=limit))


@app.command("positions")
def positions(
    user: UsernameOption,
    mark: MarkOption = None,
) -> None:
    """Calculate current holdings."""

    _run_json(lambda: _store_service().positions(username=user, marks=parse_marks(mark or [])))


@app.command("summary")
def summary(
    user: UsernameOption,
    mark: MarkOption = None,
) -> None:
    """Calculate portfolio return summary."""

    _run_json(lambda: _store_service().summary(username=user, marks=parse_marks(mark or [])))


def _store_service() -> StoreService:
    """Create the store service and ensure local tables exist."""

    context = create_application_context()
    context.database.create_schema()
    return StoreService(database=context.database, clock=context.clock)


def _admin_store_service(admin_token: str) -> StoreService:
    """Create a store service after validating the admin token."""

    context = create_application_context()
    if admin_token != context.settings.store_admin_token:
        raise ValidationError("invalid admin token")
    context.database.create_schema()
    return StoreService(database=context.database, clock=context.clock)


def parse_decimal(value: str, field: str) -> Decimal:
    """Parse a CLI decimal value without using float conversion."""

    try:
        return Decimal(value)
    except Exception as exc:
        raise ValidationError(f"{field} must be a decimal number") from exc


def _run_json(operation: Callable[[], dict[str, object]]) -> None:
    """Run a store operation and emit a single JSON object."""

    try:
        payload = operation()
        _echo_json(payload)
    except AMStockError as exc:
        _echo_json({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}})
        raise typer.Exit(1) from exc
    except Exception as exc:
        _echo_json({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}})
        raise typer.Exit(1) from exc


def _echo_json(payload: dict[str, object]) -> None:
    typer.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True))


admin_app.add_typer(admin_user_app, name="user")
app.add_typer(admin_app, name="admin")
app.add_typer(trade_app, name="trade")


def main() -> None:
    """Run the local store CLI."""

    app()


if __name__ == "__main__":
    main()
