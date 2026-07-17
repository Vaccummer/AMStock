"""CLI commands for importing and querying full-market snapshots."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

from amstock.exceptions import ValidationError
from amstock.market_snapshot_io import parse_market_snapshot_file
from amstock.services import create_application_context
from amstock.services.market_snapshot import (
    MarketSnapshotService,
    validate_snapshot_date,
)

if TYPE_CHECKING:
    from collections.abc import Callable


app = typer.Typer(no_args_is_help=True)


@app.command("import")
def import_snapshot(
    file: Annotated[str | None, typer.Option("--file")] = None,
    snapshot_date: Annotated[str | None, typer.Option("--date")] = None,
) -> None:
    """Parse a complete market export, then import it for one date."""

    _run_json(lambda: _import_records(file=file, snapshot_date=snapshot_date))


@app.command("list")
def list_snapshot(
    snapshot_date: Annotated[str | None, typer.Option("--date")] = None,
    code: Annotated[str | None, typer.Option("--code")] = None,
    name: Annotated[str | None, typer.Option("--name")] = None,
    industry: Annotated[str | None, typer.Option("--industry")] = None,
    min_change: Annotated[str | None, typer.Option("--min-change")] = None,
    max_change: Annotated[str | None, typer.Option("--max-change")] = None,
    min_turnover: Annotated[str | None, typer.Option("--min-turnover")] = None,
    max_turnover: Annotated[str | None, typer.Option("--max-turnover")] = None,
    min_pe: Annotated[str | None, typer.Option("--min-pe")] = None,
    max_pe: Annotated[str | None, typer.Option("--max-pe")] = None,
    min_market_cap: Annotated[str | None, typer.Option("--min-market-cap")] = None,
    max_market_cap: Annotated[str | None, typer.Option("--max-market-cap")] = None,
    sort_by: Annotated[str, typer.Option("--sort-by")] = "stock_code",
    order: Annotated[str, typer.Option("--order")] = "asc",
    limit: Annotated[str, typer.Option("--limit")] = "100",
) -> None:
    """List a dated snapshot using exact text and numeric filters."""

    _run_json(
        lambda: _service().list_records(
            snapshot_date=_resolve_snapshot_date(snapshot_date),
            code=code,
            name=name,
            industry=industry,
            min_change=_parse_decimal(min_change, option="--min-change"),
            max_change=_parse_decimal(max_change, option="--max-change"),
            min_turnover=_parse_decimal(min_turnover, option="--min-turnover"),
            max_turnover=_parse_decimal(max_turnover, option="--max-turnover"),
            min_pe=_parse_decimal(min_pe, option="--min-pe"),
            max_pe=_parse_decimal(max_pe, option="--max-pe"),
            min_market_cap=_parse_decimal(
                min_market_cap, option="--min-market-cap"
            ),
            max_market_cap=_parse_decimal(
                max_market_cap, option="--max-market-cap"
            ),
            sort_by=sort_by,
            order=order,  # type: ignore[arg-type]
            limit=_parse_limit(limit),
        )
    )


def _import_records(
    *, file: str | None, snapshot_date: str | None
) -> dict[str, object]:
    """Parse the complete source before constructing the persistence service."""

    if file is None:
        raise ValidationError("--file is required")
    normalized_date = _resolve_snapshot_date(snapshot_date)
    path = Path(file).expanduser()
    if not path.is_file():
        raise ValidationError(f"market snapshot file does not exist: {path}")
    records = parse_market_snapshot_file(path)
    return _service().import_records(
        snapshot_date=normalized_date,
        records=records,
    )


def _resolve_snapshot_date(value: str | None) -> str:
    """Return an explicit valid date or the current local date."""

    return validate_snapshot_date(value if value is not None else date.today().isoformat())


def _parse_decimal(value: str | None, *, option: str) -> Decimal | None:
    """Parse a finite raw decimal inside the JSON error boundary."""

    if value is None:
        return None
    try:
        decimal = Decimal(value)
    except InvalidOperation as exc:
        raise ValidationError(f"{option} must be a decimal") from exc
    if not decimal.is_finite():
        raise ValidationError(f"{option} must be a finite decimal")
    return decimal


def _parse_limit(value: str) -> int:
    """Parse the raw result limit inside the JSON error boundary."""

    try:
        return int(value)
    except ValueError as exc:
        raise ValidationError("limit must be an integer") from exc


def _service() -> MarketSnapshotService:
    """Create the snapshot service and ensure its tables exist."""

    context = create_application_context()
    context.database.create_schema()
    return MarketSnapshotService(database=context.database, clock=context.clock)


def _run_json(operation: Callable[[], dict[str, object]]) -> None:
    """Emit one JSON object for both successful results and command errors."""

    try:
        _echo_json(operation())
    except Exception as exc:
        _echo_json({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}})
        raise typer.Exit(1) from exc


def _echo_json(payload: dict[str, object]) -> None:
    typer.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True))
