"""Tests for news API helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from amstock import news_io

if TYPE_CHECKING:
    from pathlib import Path


def test_marketaux_payload_redacts_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Marketaux tokens stay out of params and URL metadata."""

    def fake_request_json(
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float,
        proxy_url: str | None = None,
    ) -> dict[str, object]:
        assert "api_token=secret-token" in url
        assert headers is None
        assert timeout == 5
        assert proxy_url is None
        return {"meta": {"found": 2}, "data": [{"title": "one"}]}

    monkeypatch.setattr(news_io, "request_json", fake_request_json)

    payload = news_io.fetch_marketaux_news(
        params={"search": "oil", "symbols": "USO"},
        token_value="secret-token",
        base_url="https://example.test",
        timeout=5,
        limit=1,
        proxy_url="",
    )

    assert payload["function"] == "marketaux-news-all"
    assert payload["params"] == {"search": "oil", "symbols": "USO", "limit": 1}
    assert payload["rows"] == 2
    assert payload["returned_rows"] == 1
    assert "secret-token" not in str(payload["url"])
    assert "api_token=***" in str(payload["url"])


def test_gdelt_payload_uses_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """GDELT Cloud tokens are sent as bearer auth headers."""

    def fake_request_json(
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float,
        proxy_url: str | None = None,
    ) -> dict[str, object]:
        assert url == "https://example.test/api/v2/events?search=rates&country=US&limit=3"
        assert headers == {"Authorization": "Bearer gdelt-token"}
        assert timeout == 7
        assert proxy_url is None
        return {"events": [{"title": "one"}, {"title": "two"}]}

    monkeypatch.setattr(news_io, "request_json", fake_request_json)

    payload = news_io.fetch_gdelt_news(
        endpoint="events",
        params={"search": "rates", "country": "US"},
        token_value="gdelt-token",
        base_url="https://example.test",
        timeout=7,
        limit=3,
        proxy_url="",
    )

    assert payload["function"] == "gdelt-events"
    assert payload["rows"] == 2
    assert payload["params"] == {"search": "rates", "country": "US", "limit": 3}


def test_news_tokens_can_read_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """News API tokens can be loaded from AMSTOCK_HOME config."""

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        """
[database]
path = "data/test.sqlite3"

[credentials.news]
gdelt_cloud_token = "gdelt-config"
marketaux_token = "marketaux-config"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("AMSTOCK_HOME", str(tmp_path))
    monkeypatch.delenv("AMSTOCK_GDELT_CLOUD_TOKEN", raising=False)
    monkeypatch.delenv("AMSTOCK_MARKETAUX_TOKEN", raising=False)

    assert news_io.resolve_gdelt_token() == "gdelt-config"
    assert news_io.resolve_marketaux_token() == "marketaux-config"


def test_news_tokens_can_read_multiple_config_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """News API tokens can be configured as arrays."""

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        """
[database]
path = "data/test.sqlite3"

[credentials.news]
gdelt_cloud_tokens = ["gdelt-1", "gdelt-2"]
marketaux_tokens = ["marketaux-1", "marketaux-2"]
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("AMSTOCK_HOME", str(tmp_path))
    monkeypatch.delenv("AMSTOCK_GDELT_CLOUD_TOKEN", raising=False)
    monkeypatch.delenv("AMSTOCK_MARKETAUX_TOKEN", raising=False)

    assert news_io.resolve_gdelt_token() == "gdelt-1"
    assert news_io.resolve_marketaux_token() == "marketaux-1"


def test_news_proxy_can_read_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """News API proxy can be loaded from AMSTOCK_HOME config."""

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        """
[database]
path = "data/test.sqlite3"

[credentials.news]
proxy_url = "http://127.0.0.1:7897"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("AMSTOCK_HOME", str(tmp_path))
    monkeypatch.delenv("AMSTOCK_NEWS_PROXY", raising=False)

    assert news_io.resolve_news_proxy() == "http://127.0.0.1:7897"


def test_news_token_requires_value(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing news API tokens fail before HTTP requests are attempted."""

    monkeypatch.setenv("AMSTOCK_HOME", str(tmp_path))
    monkeypatch.delenv("AMSTOCK_GDELT_CLOUD_TOKEN", raising=False)

    with pytest.raises(ValueError, match="GDELT Cloud token is required"):
        news_io.resolve_gdelt_token()
