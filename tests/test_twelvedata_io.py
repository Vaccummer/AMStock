"""Tests for Twelve Data helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from amstock import twelvedata_io

if TYPE_CHECKING:
    from pathlib import Path


def test_quote_payload_redacts_api_key_and_passes_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Twelve Data API keys stay out of returned metadata."""

    def fake_request_json(
        url: str,
        *,
        timeout: float,
        proxy_url: str | None = None,
    ) -> dict[str, object]:
        assert url == "https://example.test/quote?symbol=NVDA&apikey=secret-key"
        assert timeout == 5
        assert proxy_url == "http://127.0.0.1:7897"
        return {"symbol": "NVDA", "close": "180.00"}

    monkeypatch.setattr(twelvedata_io, "request_json", fake_request_json)

    payload = twelvedata_io.fetch_twelvedata_quote(
        symbol="nvda",
        api_key="secret-key",
        base_url="https://example.test",
        timeout=5,
        proxy_url="http://127.0.0.1:7897",
    )

    assert payload["function"] == "quote"
    assert payload["params"] == {"symbol": "NVDA"}
    assert payload["rows"] == 1
    assert "secret-key" not in str(payload["url"])
    assert "apikey=***" in str(payload["url"])


def test_time_series_counts_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """Historical bars report the number of returned values."""

    def fake_request_json(
        url: str,
        *,
        timeout: float,
        proxy_url: str | None = None,
    ) -> dict[str, object]:
        assert "symbol=MSFT" in url
        assert "interval=1day" in url
        assert "outputsize=2" in url
        assert timeout == 20
        assert proxy_url is None
        return {
            "meta": {"symbol": "MSFT"},
            "values": [{"datetime": "2026-06-10"}, {"datetime": "2026-06-09"}],
        }

    monkeypatch.setattr(twelvedata_io, "request_json", fake_request_json)

    payload = twelvedata_io.fetch_twelvedata_time_series(
        symbol="MSFT",
        interval="1day",
        outputsize=2,
        api_key="secret-key",
        base_url="https://example.test",
        timeout=20,
    )

    assert payload["rows"] == 2
    assert payload["returned_rows"] == 2


def test_twelvedata_key_and_proxy_can_read_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Twelve Data credentials can be loaded from AMSTOCK_HOME config."""

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        """
[database]
path = "data/test.sqlite3"

[credentials.twelvedata]
api_key = "config-key"
base_url = "https://config.example.test"
timeout = 11
proxy_url = "http://127.0.0.1:7897"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("AMSTOCK_HOME", str(tmp_path))
    monkeypatch.delenv("AMSTOCK_TWELVEDATA_API_KEY", raising=False)
    monkeypatch.delenv("AMSTOCK_TWELVEDATA_PROXY", raising=False)

    assert twelvedata_io.resolve_twelvedata_api_key() == "config-key"
    assert twelvedata_io.resolve_twelvedata_base_url() == "https://config.example.test"
    assert twelvedata_io.resolve_twelvedata_timeout() == 11
    assert twelvedata_io.resolve_twelvedata_proxy() == "http://127.0.0.1:7897"


def test_twelvedata_key_can_read_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Environment variables can provide Twelve Data credentials."""

    monkeypatch.setenv("AMSTOCK_TWELVEDATA_API_KEY", "env-key")
    monkeypatch.setenv("AMSTOCK_TWELVEDATA_PROXY", "http://127.0.0.1:7898")

    assert twelvedata_io.resolve_twelvedata_api_key() == "env-key"
    assert twelvedata_io.resolve_twelvedata_proxy() == "http://127.0.0.1:7898"


def test_twelvedata_key_requires_value(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing Twelve Data keys fail before HTTP requests are attempted."""

    monkeypatch.setenv("AMSTOCK_HOME", str(tmp_path))
    monkeypatch.delenv("AMSTOCK_TWELVEDATA_API_KEY", raising=False)

    with pytest.raises(ValueError, match="Twelve Data API key is required"):
        twelvedata_io.resolve_twelvedata_api_key()


def test_twelvedata_api_error_raises_value_error() -> None:
    """Twelve Data error payloads become command failures."""

    with pytest.raises(ValueError, match="API credits exceeded"):
        twelvedata_io.ensure_twelvedata_success(
            {"status": "error", "message": "API credits exceeded", "code": 429},
        )
