"""CLI commands for importing and querying sector capital-flow snapshots."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path  # noqa: TC003 -- Typer evaluates command annotations at runtime.
from typing import TYPE_CHECKING, Annotated, Literal

import typer

from amstock.sector_flow_io import parse_sector_flow_file
from amstock.services import create_application_context
from amstock.services.sector_flow import SectorFlowService, validate_flow_date

if TYPE_CHECKING:
    from collections.abc import Callable


app = typer.Typer(no_args_is_help=True)


@app.command("import")
def import_flow(
    file: Annotated[Path, typer.Option("--file", exists=True, readable=True)],
    flow_date: Annotated[str | None, typer.Option("--date")] = None,
) -> None:
    """Parse a sector-flow export, then import its complete snapshot."""

    _run_json(lambda: _import_records(file=file, flow_date=flow_date))


@app.command("list")
def list_flow(
    flow_date: Annotated[str | None, typer.Option("--date")] = None,
    code: Annotated[str | None, typer.Option("--code")] = None,
    direction: Annotated[Literal["in", "out"] | None, typer.Option("--direction")] = None,
    limit: Annotated[int | None, typer.Option("--limit")] = None,
) -> None:
    """List saved sector-flow snapshots for one date."""

    _run_json(
        lambda: _service().list_records(
            flow_date=_resolve_flow_date(flow_date),
            sector_code=code,
            direction=direction,
            limit=limit,
        )
    )


def _import_records(*, file: Path, flow_date: str | None) -> dict[str, object]:
    """Parse all input before constructing the persistence service."""

    normalized_date = _resolve_flow_date(flow_date)
    records = parse_sector_flow_file(file)
    return _service().import_records(flow_date=normalized_date, records=records)


def _resolve_flow_date(value: str | None) -> str:
    """Return an explicit valid date or the current local date."""

    return validate_flow_date(value if value is not None else date.today().isoformat())


def _service() -> SectorFlowService:
    """Create the sector-flow service and ensure its tables exist."""

    context = create_application_context()
    context.database.create_schema()
    return SectorFlowService(database=context.database, clock=context.clock)


def _run_json(operation: Callable[[], dict[str, object]]) -> None:
    """Run an operation and emit one JSON object, including command errors."""

    try:
        _echo_json(operation())
    except Exception as exc:
        _echo_json({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}})
        raise typer.Exit(1) from exc


def _echo_json(payload: dict[str, object]) -> None:
    typer.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True))
