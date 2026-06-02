"""Tests for the agent-facing source data CLI."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from amstock import src_cli
from amstock.src_queries import capabilities_payload

if TYPE_CHECKING:
    import pytest


def test_capabilities_payload_lists_agent_contract() -> None:
    """Capabilities are machine-readable and include the supported command set."""

    payload = capabilities_payload()

    assert payload["ok"] is True
    assert payload["cli"] == "amstock_src"
    assert payload["output"] == (
        "single JSON object on stdout; failed commands also emit JSON and exit non-zero"
    )

    commands = {command["name"] for command in payload["commands"]}
    assert "price-history" in commands
    assert "financial-report" in commands
    assert "concept-list" in payload["unsupported_now"]


def test_capabilities_command_emits_json() -> None:
    """The CLI capabilities command emits one JSON object."""

    result = CliRunner().invoke(src_cli.app, ["capabilities"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["cli"] == "amstock_src"


def test_query_command_emits_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """Query commands route through package functions and keep JSON output."""

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
            "function": "fake",
            "params": {
                "symbol": symbol,
                "limit": limit,
                "no_proxy": no_proxy,
                "ipv4": ipv4,
            },
            "data": [],
        }

    monkeypatch.setattr(src_cli, "fetch_stock_basic", fake_fetch_stock_basic)

    result = CliRunner().invoke(
        src_cli.app,
        ["stock-basic", "--symbol", "600519", "--limit", "2", "--no-proxy", "--ipv4"],
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
