"""Tests for the unified AMStock CLI."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from amstock import cli

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

ADMIN_TOKEN = "test-admin-token"


def test_unified_stock_basic_command_routes_to_source_function(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The unified stock command keeps the JSON source-query contract."""

    def fake_fetch_stock_basic(
        *,
        symbol: str,
        limit: int | None,
        no_proxy: bool,
        ipv4: bool,
    ) -> dict[str, object]:
        return {
            "ok": True,
            "source": "test",
            "function": "stock-basic",
            "params": {
                "symbol": symbol,
                "limit": limit,
                "no_proxy": no_proxy,
                "ipv4": ipv4,
            },
            "data": [],
        }

    monkeypatch.setattr(cli, "fetch_stock_basic", fake_fetch_stock_basic)

    result = CliRunner().invoke(
        cli.app,
        ["stock", "basic", "--symbol", "600519", "--limit", "2", "--no-proxy", "--ipv4"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["params"] == {
        "symbol": "600519",
        "limit": 2,
        "no_proxy": True,
        "ipv4": True,
    }


def test_unified_quote_pool_routes_to_biying(monkeypatch: pytest.MonkeyPatch) -> None:
    """Quote pool commands use the Biying dataset mapper."""

    def fake_fetch_biying_dataset(
        *,
        dataset: str,
        params: dict[str, str | int | None],
        licences_value: str | None,
        base_url: str,
        timeout: float,
        limit: int | None,
    ) -> dict[str, object]:
        return {
            "ok": True,
            "source": "biying-test",
            "function": dataset,
            "params": params,
            "licences_value": licences_value,
            "base_url": base_url,
            "timeout": timeout,
            "limit": limit,
            "data": [],
        }

    monkeypatch.setattr(cli, "fetch_biying_dataset", fake_fetch_biying_dataset)

    result = CliRunner().invoke(
        cli.app,
        [
            "quote",
            "pool",
            "--kind",
            "limit-up",
            "--date",
            "2024-01-10",
            "--licences",
            "alpha,beta",
            "--limit",
            "3",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["function"] == "limit-up-pool"
    assert payload["params"] == {"date": "2024-01-10"}
    assert payload["licences_value"] == "alpha,beta"
    assert payload["limit"] == 3


def test_unified_sources_capabilities_keeps_legacy_source_app() -> None:
    """The old source CLI is available under the unified sources namespace."""

    result = CliRunner().invoke(cli.app, ["sources", "capabilities"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["cli"] == "amstock_src"


def test_unified_portfolio_namespace_mounts_store_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The portfolio namespace exposes the existing store commands."""

    configure_amstock_root(tmp_path, monkeypatch)
    runner = CliRunner()

    create = runner.invoke(
        cli.app,
        [
            "portfolio",
            "admin",
            "user",
            "create",
            "--username",
            "alice",
            "--admin-token",
            ADMIN_TOKEN,
        ],
    )
    assert create.exit_code == 0

    buy = runner.invoke(
        cli.app,
        [
            "portfolio",
            "trade",
            "buy",
            "--user",
            "alice",
            "--symbol",
            "600519",
            "--quantity",
            "100",
            "--price",
            "10",
        ],
    )
    assert buy.exit_code == 0

    summary = runner.invoke(
        cli.app,
        ["portfolio", "summary", "--user", "alice", "--mark", "600519=12"],
    )

    assert summary.exit_code == 0
    payload = json.loads(summary.stdout)
    assert payload["ok"] is True
    assert payload["positions"][0]["quantity"] == "100.0000"


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
