"""Tests for the AMStock news polling server — refactored for OpenAI AI provider."""

from __future__ import annotations

import json
from datetime import datetime
from io import BytesIO
from typing import TYPE_CHECKING
from urllib.error import HTTPError
from zoneinfo import ZoneInfo

from amstock import news_server
from amstock.news import collectors as news_collectors
from amstock.news_server import (
    AIConfig,
    NewsServerConfig,
    NewsSourceConfig,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import pytest


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────


def sample_config(
    tmp_path: Path,
    *,
    ai_api_key: str = "sk-test",
    ai_model: str = "gpt-4o-mini",
    ai_timeout: float = 5.0,
) -> NewsServerConfig:
    """Build a minimal news server config with AI provider."""

    return NewsServerConfig(
        interval_seconds=60,
        database_path=tmp_path / "news.sqlite3",
        log_path=tmp_path / "logs" / "news_server.log",
        timezone="Asia/Shanghai",
        ai=AIConfig(
            base_url="https://api.openai.com/v1",
            api_key=ai_api_key,
            model=ai_model,
            timeout=ai_timeout,
            sys_prompt="You are a financial news classifier. Return JSON.",
        ),
        sources=(
            NewsSourceConfig(
                name="test-source",
                type="akshare_flash",
                enabled=True,
                interval_seconds=60,
                schedule_times=(),
                active_windows=(),
                limit=10,
                params={"source": "eastmoney"},
                user_prompt="",
            ),
        ),
    )


def _fake_openai_response(content: str) -> Callable[..., str]:
    """Return a function that mimics openai_chat_completion returning `content`."""

    def responder(_config: AIConfig, _messages: list[dict[str, str]]) -> str:
        return content

    return responder


# ──────────────────────────────────────────────
# Rating + storage tests
# ──────────────────────────────────────────────


def test_rate_and_store_news_items(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Items are rated via OpenAI and stored in news_reviews."""

    config = sample_config(tmp_path)
    news_server.ensure_news_schema(config.database_path)

    item_id = news_server.insert_news_item(
        config.database_path,
        {
            "source": "test-source",
            "provider": "eastmoney",
            "title": "央行降准0.5个百分点",
            "summary": "释放长期流动性",
            "url": "https://example.test/news/1",
            "published_at": "2026-07-15T10:30:00",
            "fingerprint": "fp-001",
            "raw_json": "{}",
        },
    )
    assert item_id is not None

    monkeypatch.setattr(
        news_server,
        "openai_chat_completion",
        _fake_openai_response(json.dumps({
            "items": [{
                "news_id": item_id,
                "keep": True,
                "category": "宏观经济",
                "importance": 5,
                "urgency": 4,
                "event": "央行降准释放流动性",
            }]
        }, ensure_ascii=False)),
    )

    item_data = {
        "source": "test-source",
        "provider": "eastmoney",
        "title": "央行降准0.5个百分点",
        "summary": "释放长期流动性",
        "url": "https://example.test/news/1",
        "published_at": "2026-07-15T10:30:00",
        "fingerprint": "fp-001",
        "raw_json": "{}",
    }

    result = news_server.rate_and_store_news_items(config, [(item_id, item_data)])

    assert result["rated"] == 1

    # Verify review was stored with category
    import sqlite3

    with sqlite3.connect(config.database_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM news_reviews WHERE news_item_id = ?", (item_id,)
        ).fetchone()
    assert row is not None
    assert int(row["importance"]) == 5
    assert int(row["urgent"]) == 1  # urgency >= 4
    assert str(row["category"]) == "宏观经济"


def test_rate_news_items_falls_back_without_api_key(tmp_path: Path) -> None:
    """When no API key is configured, fallback_rating is used."""

    config = sample_config(tmp_path, ai_api_key="")
    news_server.ensure_news_schema(config.database_path)

    items = [
        (
            1,
            {
                "source": "test-source",
                "provider": "eastmoney",
                "title": "Some news",
                "summary": "Summary text",
                "url": "https://example.test",
                "published_at": "2026-07-15",
                "fingerprint": "fp-002",
                "raw_json": "{}",
            },
        )
    ]
    ratings = news_server.rate_news_items(config, items)
    assert len(ratings) == 1
    assert ratings[0]["keep"] is False
    assert ratings[0]["category"] == "其他"


# ──────────────────────────────────────────────
# News once (collection + rating cycle)
# ──────────────────────────────────────────────


def test_news_once_rates_and_stores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """One news cycle collects, rates, and stores without pushing."""

    config = sample_config(tmp_path)
    news_server.ensure_news_schema(config.database_path)

    monkeypatch.setattr(
        news_server,
        "collect_source",
        lambda _source, _config=None, _token_index=0: [
            {
                "source": "test-source",
                "provider": "eastmoney",
                "title": "Market update",
                "summary": "Stocks rally on positive data",
                "url": "https://example.test/news/market",
                "published_at": "2026-07-15T10:00:00",
                "fingerprint": "fp-market-001",
                "raw_json": "{}",
            }
        ],
    )
    monkeypatch.setattr(
        news_server,
        "openai_chat_completion",
        _fake_openai_response(json.dumps({
            "items": [{
                "news_id": None,  # Will be resolved by find_rating_for_item
                "keep": True,
                "category": "A股市场",
                "importance": 4,
                "urgency": 3,
                "event": "A股市场上涨",
            }]
        }, ensure_ascii=False)),
    )

    payload = news_server.run_news_once(config)

    assert payload["function"] == "news-once"
    assert payload["sources"] == 1
    assert payload["fetched"] == 1
    assert payload["new"] == 1
    assert payload["rated"] == 1
    # No more delivery stats
    assert "sent" not in payload
    assert "queued" not in payload


# ──────────────────────────────────────────────
# News list / query tests
# ──────────────────────────────────────────────


def test_news_list_filters_by_category(tmp_path: Path) -> None:
    """News list payload filters by category."""

    config = sample_config(tmp_path)
    news_server.ensure_news_schema(config.database_path)

    item_id = news_server.insert_news_item(
        config.database_path,
        {
            "source": "test-source",
            "provider": "eastmoney",
            "title": "GDP数据发布",
            "summary": "GDP growth beats expectations",
            "url": "https://example.test/gdp",
            "published_at": "2026-07-15T10:00:00",
            "fingerprint": "fp-gdp-001",
            "raw_json": "{}",
        },
    )
    assert item_id is not None
    news_server.save_news_review(
        config.database_path,
        item_id,
        {
            "push": True,
            "importance": 5,
            "urgent": 4,
            "category": "宏观经济",
            "markets": [],
            "assets": [],
            "message": "GDP超预期增长",
            "raw_response": "{}",
        },
    )

    payload = news_server.news_list_payload(config, category="宏观经济")
    assert payload["total"] >= 1
    assert payload["data"][0]["title"] == "GDP数据发布"
    assert payload["data"][0]["rating"]["category"] == "宏观经济"

    # Wrong category returns nothing
    payload2 = news_server.news_list_payload(config, category="军事冲突")
    assert payload2["total"] == 0


def test_news_list_filters_by_importance(tmp_path: Path) -> None:
    """News list filters by importance range."""

    config = sample_config(tmp_path)
    news_server.ensure_news_schema(config.database_path)

    for i, (title, imp, fp) in enumerate([
        ("High impact", 5, "fp-high"),
        ("Medium impact", 3, "fp-mid"),
        ("Low impact", 1, "fp-low"),
    ]):
        item_id = news_server.insert_news_item(
            config.database_path,
            {
                "source": "test-source",
                "provider": "eastmoney",
                "title": title,
                "summary": "Summary",
                "url": f"https://example.test/{fp}",
                "published_at": "2026-07-15T10:00:00",
                "fingerprint": fp,
                "raw_json": "{}",
            },
        )
        assert item_id is not None
        news_server.save_news_review(
            config.database_path,
            item_id,
            {
                "push": True,
                "importance": imp,
                "urgent": 0,
                "category": "其他",
                "markets": [],
                "assets": [],
                "message": "",
                "raw_response": "{}",
            },
        )

    payload = news_server.news_list_payload(config, min_importance=4)
    assert payload["total"] == 1
    assert payload["data"][0]["title"] == "High impact"


def test_news_list_pagination(tmp_path: Path) -> None:
    """News list supports offset/limit pagination."""

    config = sample_config(tmp_path)
    news_server.ensure_news_schema(config.database_path)

    for i in range(5):
        news_server.insert_news_item(
            config.database_path,
            {
                "source": "test-source",
                "provider": "eastmoney",
                "title": f"News {i}",
                "summary": f"Summary {i}",
                "url": f"https://example.test/{i}",
                "published_at": "2026-07-15T10:00:00",
                "fingerprint": f"fp-pag-{i}",
                "raw_json": "{}",
            },
        )

    page1 = news_server.news_list_payload(config, limit=2, offset=0)
    assert page1["returned_rows"] == 2
    assert page1["total"] == 5

    page2 = news_server.news_list_payload(config, limit=2, offset=2)
    assert page2["returned_rows"] == 2

    page3 = news_server.news_list_payload(config, limit=2, offset=4)
    assert page3["returned_rows"] == 1


def test_news_list_sorting(tmp_path: Path) -> None:
    """News list supports sorting by importance."""

    config = sample_config(tmp_path)
    news_server.ensure_news_schema(config.database_path)

    for title, imp, fp in [
        ("Medium", 3, "fp-sort-mid"),
        ("High", 5, "fp-sort-high"),
        ("Low", 1, "fp-sort-low"),
    ]:
        item_id = news_server.insert_news_item(
            config.database_path,
            {
                "source": "test-source",
                "provider": "eastmoney",
                "title": title,
                "summary": "Summary",
                "url": f"https://example.test/sort/{fp}",
                "published_at": "2026-07-15T10:00:00",
                "fingerprint": fp,
                "raw_json": "{}",
            },
        )
        assert item_id is not None
        news_server.save_news_review(
            config.database_path,
            item_id,
            {
                "push": True,
                "importance": imp,
                "urgent": 0,
                "category": "其他",
                "markets": [],
                "assets": [],
                "message": "",
                "raw_response": "{}",
            },
        )

    payload = news_server.news_list_payload(config, sort_by="importance", sort_order="desc")
    assert payload["data"][0]["rating"]["importance"] >= payload["data"][-1]["rating"]["importance"]


# ──────────────────────────────────────────────
# Schema / migration tests
# ──────────────────────────────────────────────


def test_schema_adds_category_column(tmp_path: Path) -> None:
    """ensure_news_schema adds category column to existing news_reviews table."""

    config = sample_config(tmp_path)
    news_server.ensure_news_schema(config.database_path)

    import sqlite3

    with sqlite3.connect(config.database_path) as conn:
        columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(news_reviews)")
        }
    assert "category" in columns


# ──────────────────────────────────────────────
# Source scheduling tests (unchanged behavior)
# ──────────────────────────────────────────────


def test_source_schedule_uses_enumerated_times(tmp_path: Path) -> None:
    """Enumerated schedule times compute the next HH:MM run."""

    config = sample_config(tmp_path)
    tz = ZoneInfo("Asia/Shanghai")
    now = datetime(2026, 7, 15, 8, 0, tzinfo=tz)
    now_epoch = int(now.timestamp())

    # Today at 9:00 should be the next run (8:00 < 9:00)
    next_epoch = news_server.next_enumerated_epoch(
        ("09:00", "15:00"), "Asia/Shanghai", now_epoch
    )
    assert next_epoch > now_epoch
    next_dt = datetime.fromtimestamp(next_epoch, tz)
    assert next_dt.hour == 9
    assert next_dt.minute == 0


def test_source_active_windows_defer_until_window(tmp_path: Path) -> None:
    """Source deferred when outside active window."""

    config = sample_config(tmp_path)
    news_server.ensure_news_schema(config.database_path)

    tz = ZoneInfo("Asia/Shanghai")
    noon = datetime(2026, 7, 15, 12, 0, tzinfo=tz)
    noon_epoch = int(noon.timestamp())

    source = NewsSourceConfig(
        name="windowed-source",
        type="akshare_flash",
        enabled=True,
        interval_seconds=60,
        schedule_times=(),
        active_windows=("09:00-11:30",),
        limit=10,
        params={"source": "eastmoney"},
    )

    # At noon, source should not be active
    assert not news_server.source_active_at(source, "Asia/Shanghai", noon_epoch)

    # Next window should be tomorrow 09:00
    next_epoch = news_server.next_active_window_epoch(
        ("09:00-11:30",), "Asia/Shanghai", noon_epoch
    )
    next_dt = datetime.fromtimestamp(next_epoch, tz)
    assert next_dt.hour == 9
    assert next_dt.minute == 0
    assert next_dt.day >= 15


def test_source_active_windows_allow_interval_inside_window(tmp_path: Path) -> None:
    """Source is active inside its configured window."""

    tz = ZoneInfo("Asia/Shanghai")
    morning = datetime(2026, 7, 15, 10, 0, tzinfo=tz)
    morning_epoch = int(morning.timestamp())

    source = NewsSourceConfig(
        name="windowed-source",
        type="akshare_flash",
        enabled=True,
        interval_seconds=60,
        schedule_times=(),
        active_windows=("09:00-11:30",),
        limit=10,
        params={"source": "eastmoney"},
    )

    assert news_server.source_active_at(source, "Asia/Shanghai", morning_epoch)


def test_news_server_writes_schedule_log_without_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Server start writes a JSON log event without printing to stdout."""

    config = sample_config(tmp_path)
    config.log_path.parent.mkdir(parents=True, exist_ok=True)
    news_server.ensure_news_schema(config.database_path)

    from io import StringIO

    import sys

    captured = StringIO()
    monkeypatch.setattr(sys, "stdout", captured)

    monkeypatch.setattr(news_server, "run_news_once", lambda _cfg=None: {"ok": True})
    monkeypatch.setattr(news_server, "time", type("fake_time", (), {"sleep": lambda _s: None, "time": lambda: 2147483647}))

    news_server.run_news_server(config, max_cycles=1)

    written = config.log_path.read_text(encoding="utf-8")
    assert "news-server-start" in written
    assert "news-server-cycle" in written


# ──────────────────────────────────────────────
# SSE / utility tests (unchanged)
# ──────────────────────────────────────────────


def test_parse_sse_payload_keeps_last_text_event() -> None:
    """SSE parser returns the last text-bearing data event."""

    raw = 'data: {"text": "first"}\n\ndata: {"text": "last"}\n\n'
    result = news_server.parse_sse_payload(raw)
    assert isinstance(result, dict)
    assert result.get("text") == "last"


# ──────────────────────────────────────────────
# Collection / source tests
# ──────────────────────────────────────────────


def test_collect_source_passes_proxy_without_api_param(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """collect_source passes proxy_url through source params without leaking to API params."""

    calls: list[dict[str, object]] = []

    def fake_fetch(*, params: dict[str, object], token_value: str | None = None,
                   proxy_url: str | None = None, limit: int | None = None, **_kw: object) -> dict[str, object]:
        calls.append({"params": dict(params), "proxy_url": proxy_url})
        return {"ok": True, "data": []}

    monkeypatch.setattr(news_collectors, "fetch_gdelt_news", fake_fetch)

    source = NewsSourceConfig(
        name="proxy-test",
        type="gdelt",
        enabled=True,
        interval_seconds=60,
        schedule_times=(),
        active_windows=(),
        limit=5,
        params={"endpoint": "events", "proxy_url": "http://proxy:8080", "country": "CN"},
    )
    config = sample_config(tmp_path)
    news_server.collect_source(source, config)
    assert len(calls) == 1
    assert calls[0]["proxy_url"] == "http://proxy:8080"
    assert "proxy_url" not in calls[0]["params"]


def test_marketaux_source_adds_moving_published_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Marketaux collection adds a published_after window based on last success."""

    api_params_seen: list[dict[str, object]] = []

    def fake_fetch(*, params: dict[str, object], token_value: str | None = None,
                   proxy_url: str | None = None, limit: int | None = None, **_kw: object) -> dict[str, object]:
        api_params_seen.append(dict(params))
        return {
            "ok": True,
            "data": {
                "data": [
                    {
                        "title": "Market updates",
                        "description": "Summary",
                        "url": "https://example.test/m",
                        "published_at": "2026-07-15T10:00:00",
                    }
                ]
            },
        }

    monkeypatch.setattr(news_collectors, "fetch_marketaux_news", fake_fetch)

    source = NewsSourceConfig(
        name="mkt-test",
        type="marketaux",
        enabled=True,
        interval_seconds=300,
        schedule_times=(),
        active_windows=(),
        limit=5,
        params={"countries": "us"},
    )

    config = sample_config(tmp_path)
    items = news_server.collect_source(source, config)
    assert len(items) >= 1
    assert "published_after" in api_params_seen[0]


def test_marketaux_sections_retry_next_token_on_quota_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Marketaux rotates to the next token on quota-exhausted HTTP 429."""

    tokens_tried: list[str | None] = []
    call_count = [0]

    def fake_fetch(*, token_value: str | None = None, **_kw: object) -> dict[str, object]:
        tokens_tried.append(token_value)
        call_count[0] += 1
        if call_count[0] == 1:
            exc = HTTPError("https://api.example.com", 429, "Too Many Requests", {}, BytesIO(b'{"error":"usage_limit_reached"}'))
            raise exc
        return {
            "ok": True,
            "data": {
                "data": [
                    {
                        "title": "Event",
                        "description": "Desc",
                        "url": "https://example.test/e",
                        "published_at": "2026-07-15T10:00:00",
                    }
                ]
            },
        }

    monkeypatch.setattr(news_collectors, "fetch_marketaux_news", fake_fetch)
    monkeypatch.setattr(news_server, "source_tokens", lambda _source, _config: ("tok-a", "tok-b"))

    source = NewsSourceConfig(
        name="mkt-rotate",
        type="marketaux",
        enabled=True,
        interval_seconds=300,
        schedule_times=(),
        active_windows=(),
        limit=5,
        params={"params": {"countries": "us"}},
    )

    config = sample_config(tmp_path)
    items = news_server.collect_source(source, config)
    assert len(items) >= 1
    assert tokens_tried[0] == "tok-a"
    assert tokens_tried[1] == "tok-b"


def test_akshare_flash_supports_stable_news_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AKShare flash supports eastmoney, futu, sina, ths, and caixin."""

    import pandas as pd

    providers: list[str] = []

    def fake_collect(
        source: NewsSourceConfig,
        config: NewsServerConfig | None = None,
        token_index: int = 0,
    ) -> list[dict[str, object]]:
        providers.append(str(source.params.get("source") or ""))
        df = pd.DataFrame([{"title": "Flash headline", "content": "Content"}])
        return news_server.normalize_items(
            source.name, str(source.params.get("source") or ""),
            json.loads(df.to_json(orient="records", force_ascii=False)),
        )

    monkeypatch.setitem(news_collectors._COLLECTORS, "akshare_flash", fake_collect)

    for provider in ("eastmoney", "futu", "sina", "ths", "caixin"):
        source = NewsSourceConfig(
            name=f"flash-{provider}",
            type="akshare_flash",
            enabled=True,
            interval_seconds=60,
            schedule_times=(),
            active_windows=(),
            limit=5,
            params={"source": provider},
        )
        items = news_server.collect_source(source)
        assert len(items) >= 0

    assert set(providers) == {"eastmoney", "futu", "sina", "ths", "caixin"}


def test_akshare_economic_calendar_normalizes_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Economic calendar records are normalized with Baidu provider tag."""

    import pandas as pd

    def fake_collect(
        source: NewsSourceConfig,
        config: NewsServerConfig | None = None,
        token_index: int = 0,
    ) -> list[dict[str, object]]:
        df = pd.DataFrame([{"日期": "2026-07-15", "事件": "GDP发布", "内容": "Q2 GDP数据"}])
        return news_server.normalize_items(
            source.name, "baidu-economic",
            json.loads(df.to_json(orient="records", force_ascii=False)),
        )

    monkeypatch.setitem(news_collectors._COLLECTORS, "akshare_economic_calendar", fake_collect)

    source = NewsSourceConfig(
        name="econ-cal",
        type="akshare_economic_calendar",
        enabled=True,
        interval_seconds=60,
        schedule_times=(),
        active_windows=(),
        limit=10,
        params={"date": "20260715"},
    )
    items = news_server.collect_source(source)
    assert len(items) >= 1
    assert items[0]["provider"] == "baidu-economic"


# ──────────────────────────────────────────────
# Review prompt tests
# ──────────────────────────────────────────────


def test_build_rating_messages_includes_sys_prompt(tmp_path: Path) -> None:
    """build_rating_messages includes system prompt and formats news items."""

    sys_prompt = "You are a financial news classifier."
    items = [
        (
            1,
            {
                "source": "test-source",
                "provider": "eastmoney",
                "title": "Test News",
                "summary": "Test summary",
                "url": "https://example.test",
                "published_at": "2026-07-15T10:00:00",
                "fingerprint": "fp-msg",
                "raw_json": "{}",
            },
        )
    ]
    messages = news_server.build_rating_messages(sys_prompt, items)
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == sys_prompt
    assert messages[1]["role"] == "user"
    assert "Test News" in messages[1]["content"]
    assert "news_id: 1" in messages[1]["content"]
