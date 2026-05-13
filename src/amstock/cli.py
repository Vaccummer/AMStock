"""Command-line entry point."""

from __future__ import annotations

import json

import typer

from amstock import __version__
from amstock.exceptions import AMStockError
from amstock.services import create_application_context

app = typer.Typer(invoke_without_command=True, no_args_is_help=True)


@app.callback()
def root(
    version: bool = typer.Option(False, "--version", help="Show the application version."),
) -> None:
    """AMStock command-line interface."""

    if version:
        typer.echo(__version__)
        raise typer.Exit


@app.command("init-db")
def init_db() -> None:
    """Create database tables for the current configuration."""

    try:
        context = create_application_context()
        context.database.create_schema()
        _echo_json({"ok": True, "database_url": context.settings.database_url})
    except AMStockError as exc:
        _exit_with_error(exc)


def _exit_with_error(exc: AMStockError) -> None:
    _echo_json(
        {
            "ok": False,
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }
    )
    raise typer.Exit(1) from exc


def _echo_json(payload: dict[str, object]) -> None:
    typer.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def main() -> None:
    """Run the command-line application."""

    app()
