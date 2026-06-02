"""Tests for the amstock_store CLI."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from amstock import store_cli
from amstock.config import DEFAULT_STORE_ADMIN_TOKEN

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_store_cli_records_and_summarizes_user_portfolio(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The CLI emits JSON and persists a local user's ledger."""

    database_path = tmp_path / "store.sqlite3"
    monkeypatch.setenv("AMSTOCK_DATABASE_URL", f"sqlite:///{database_path}")
    runner = CliRunner()

    create = runner.invoke(
        store_cli.app,
        [
            "admin",
            "user",
            "create",
            "--username",
            "alice",
            "--display-name",
            "张三",
            "--admin-token",
            DEFAULT_STORE_ADMIN_TOKEN,
        ],
    )
    assert create.exit_code == 0
    assert json.loads(create.stdout)["user"]["username"] == "alice"

    buy = runner.invoke(
        store_cli.app,
        [
            "trade",
            "buy",
            "--user",
            "alice",
            "--symbol",
            "600519",
            "--name",
            "贵州茅台",
            "--quantity",
            "100",
            "--price",
            "10",
            "--fee",
            "10",
            "--date",
            "2026-01-01",
        ],
    )
    assert buy.exit_code == 0

    summary = runner.invoke(
        store_cli.app,
        ["summary", "--user", "alice", "--mark", "600519=12"],
    )

    assert summary.exit_code == 0
    payload = json.loads(summary.stdout)
    assert payload["ok"] is True
    assert payload["positions"][0]["quantity"] == "100.0000"
    assert payload["positions"][0]["unrealized_pnl"] == "190.0000"


def test_store_cli_rejects_invalid_admin_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Admin commands require the configured token."""

    database_path = tmp_path / "store.sqlite3"
    monkeypatch.setenv("AMSTOCK_DATABASE_URL", f"sqlite:///{database_path}")
    result = CliRunner().invoke(
        store_cli.app,
        [
            "admin",
            "user",
            "create",
            "--username",
            "alice",
            "--admin-token",
            "wrong-token",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["message"] == "invalid admin token"
