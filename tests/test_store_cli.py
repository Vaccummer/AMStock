"""Tests for the amstock_store CLI."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from amstock import store_cli

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

ADMIN_TOKEN = "test-admin-token"


def test_store_cli_records_and_summarizes_user_portfolio(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The CLI emits JSON and persists a local user's ledger."""

    configure_amstock_root(tmp_path, monkeypatch)
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
            ADMIN_TOKEN,
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

    configure_amstock_root(tmp_path, monkeypatch)
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


def configure_amstock_root(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Create a CLI config under a temporary AMSTOCK_ROOT."""

    config_dir = root / "config"
    config_dir.mkdir()
    (config_dir / "cli.toml").write_text(
        f"""
[database]
path = "data/store.sqlite3"

[store]
admin_token = "{ADMIN_TOKEN}"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("AMSTOCK_ROOT", str(root))
