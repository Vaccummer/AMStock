"""Tests for the AMStock news polling server."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from io import BytesIO
from types import SimpleNamespace
from typing import TYPE_CHECKING
from urllib.error import HTTPError
from zoneinfo import ZoneInfo

from amstock import news_server
from amstock.news_server import (
    AstrBotConfig,
    NewsServerConfig,
    NewsSourceConfig,
    NewsSubscriberConfig,
    QuietHoursConfig,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import pytest


def test_news_once_queues_during_quiet_hours(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One news cycle stores new items and queues subscriber delivery during quiet hours."""

    config = sample_config(tmp_path, quiet_start="00:00", quiet_end="23:59", digest_min_items=1)

    monkeypatch.setattr(
        news_server,
        "collect_source",
        lambda _source, _config=None, _token_index=0: [
            {
                "source": "test-source",
                "provider": "test",
                "title": "Rate decision",
                "summary": "Central bank cuts rates",
                "url": "https://example.test/news/1",
                "published_at": "2026-06-08T09:00:00",
                "fingerprint": "fingerprint-1",
                "raw_json": "{}",
            }
        ],
    )
    monkeypatch.setattr(news_server, "subscriber_preference_features", lambda *_args: {})
    monkeypatch.setattr(
        news_server,
        "rate_news_items",
        lambda _config, items, _subscriber, _features: [
            {
                "news_id": items[0][0],
                "keep": True,
                "category": "宏观经济",
                "importance": 5,
                "urgency": 3,
                "event": "央行降息",
                "raw_response": "{}",
            }
        ],
    )
    monkeypatch.setattr(
        news_server,
        "build_digest_message",
        lambda _config, _subscriber, _rows: "央行降息",
    )

    payload = news_server.run_news_once(config)

    assert payload["new"] == 1
    assert payload["cached"] == 1
    assert payload["queued"] == 1
    queue = news_server.news_queue_payload(config)
    assert queue["rows"] == 1
    assert queue["data"][0]["message"] == "央行降息"


def test_news_flush_sends_queued_messages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Queued messages are sent when quiet hours are over."""

    config = sample_config(tmp_path, quiet_enabled=False)
    news_server.ensure_news_schema(config.database_path)
    news_server.enqueue_delivery(
        config.database_path,
        "sub",
        "webchat:FriendMessage:user",
        1,
        "推送内容",
    )
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        news_server,
        "astrbot_send_message",
        lambda _config, umo, message: sent.append((umo, message)) or {"ok": True},
    )

    payload = news_server.flush_news_queue(config)

    assert payload["sent"] == 1
    assert sent == [("webchat:FriendMessage:user", "推送内容")]
    assert news_server.news_queue_payload(config)["rows"] == 0


def test_news_replay_reviews_stored_items(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replay reprocesses stored news without collecting new source data."""

    config = sample_config(tmp_path, quiet_enabled=False)
    news_server.ensure_news_schema(config.database_path)
    first_id = news_server.insert_news_item(
        config.database_path,
        {
            "source": "test-source",
            "provider": "test",
            "title": "Replay one",
            "summary": "Summary one",
            "url": "https://example.test/1",
            "published_at": "2026-06-08T10:00:00",
            "fingerprint": "replay-1",
            "raw_json": "{}",
        },
    )
    second_id = news_server.insert_news_item(
        config.database_path,
        {
            "source": "test-source",
            "provider": "test",
            "title": "Replay two",
            "summary": "Summary two",
            "url": "https://example.test/2",
            "published_at": "2026-06-08T10:01:00",
            "fingerprint": "replay-2",
            "raw_json": "{}",
        },
    )
    assert first_id is not None
    assert second_id is not None
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        news_server,
        "review_news_items",
        lambda _config, items, _subscriber: {
            "push": True,
            "importance": 5,
            "urgent": False,
            "markets": ["A股"],
            "assets": [],
            "message": f"重放 {len(items)} 条",
            "raw_response": "{}",
        },
    )
    monkeypatch.setattr(
        news_server,
        "astrbot_send_message",
        lambda _config, umo, message: sent.append((umo, message)) or {"ok": True},
    )

    payload = news_server.replay_news(config, limit=10)

    assert payload["function"] == "news-replay"
    assert payload["items"] == 2
    assert payload["reviewed"] == 2
    assert payload["sent"] == 1
    assert sent == [("webchat:FriendMessage:user", "重放 2 条")]


def test_news_list_filters_stored_items(tmp_path: Path) -> None:
    """Stored news can be queried by source, text, review, and delivery status."""

    config = sample_config(tmp_path, quiet_enabled=False)
    news_server.ensure_news_schema(config.database_path)
    item_id = news_server.insert_news_item(
        config.database_path,
        {
            "source": "gdelt-policy",
            "provider": "gdelt",
            "title": "OPEC output update",
            "summary": "Oil production target changed",
            "url": "https://example.test/opec",
            "published_at": "2026-06-08T10:00:00",
            "fingerprint": "list-1",
            "raw_json": "{}",
        },
    )
    assert item_id is not None
    subscriber = config.subscribers[0]
    news_server.save_news_review(
        config.database_path,
        item_id,
        {
            "push": True,
            "importance": 5,
            "urgent": False,
            "markets": ["A股"],
            "assets": [],
            "message": "OPEC 调整产量。",
            "raw_response": "{}",
        },
        subscriber,
    )
    news_server.record_delivery(
        config.database_path,
        subscriber.name,
        subscriber.umo,
        item_id,
        "OPEC 调整产量。",
        "sent",
        "",
    )

    payload = news_server.news_list_payload(
        config,
        source="gdelt-policy",
        query="OPEC",
        subscriber_name=subscriber.name,
        review_push="true",
        delivery_status="sent",
    )

    assert payload["function"] == "news-list"
    assert payload["rows"] == 1
    row = payload["data"][0]
    assert row["title"] == "OPEC output update"
    assert row["latest_review"]["push"] is True
    assert row["delivery_status"] == "sent"


def test_quiet_time_handles_cross_midnight(tmp_path: Path) -> None:
    """Quiet-hours checks handle windows that cross midnight."""

    config = sample_config(tmp_path, quiet_start="23:00", quiet_end="08:30")
    tz = ZoneInfo("Asia/Shanghai")

    assert news_server.is_quiet_time(config, datetime(2026, 6, 8, 23, 30, tzinfo=tz))
    assert news_server.is_quiet_time(config, datetime(2026, 6, 8, 7, 30, tzinfo=tz))
    assert not news_server.is_quiet_time(config, datetime(2026, 6, 8, 9, 0, tzinfo=tz))


def test_news_once_uses_subscriber_sources_and_review_sessions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Subscribers only review accepted sources and use their own review session."""

    config = sample_config(
        tmp_path,
        quiet_enabled=False,
        subscriber_sources=("gdelt-policy",),
        subscriber_prompt="只推送影响 A 股的政策和宏观新闻。",
    )
    monkeypatch.setattr(
        news_server,
        "collect_source",
        lambda _source, _config=None, _token_index=0: [
            {
                "source": "gdelt-policy",
                "provider": "gdelt",
                "title": "Tariff update",
                "summary": "New tariffs announced",
                "url": "https://example.test/news/2",
                "published_at": "2026-06-08T09:00:00",
                "fingerprint": "fingerprint-2",
                "raw_json": "{}",
            }
        ],
    )
    prompts: list[tuple[str, str, str]] = []

    def fake_chat(
        _config: AstrBotConfig,
        message: str,
        subscriber: NewsSubscriberConfig | None = None,
    ) -> str:
        assert subscriber is not None
        prompts.append((subscriber.name, subscriber.review_session_id, message))
        return json.dumps(
            {
                "items": [
                    {
                        "news_id": 1,
                        "keep": True,
                        "category": "政策监管",
                        "importance": 5,
                        "urgency": 4,
                        "event": "关税政策更新",
                    }
                ]
            },
            ensure_ascii=False,
        )

    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(news_server, "astrbot_chat", fake_chat)
    monkeypatch.setattr(
        news_server,
        "astrbot_send_message",
        lambda _config, umo, message: sent.append((umo, message)) or {"ok": True},
    )

    payload = news_server.run_news_once(config)

    assert payload["rated"] == 1
    assert payload["sent"] == 1
    assert prompts[0][0] == "sub"
    assert prompts[0][1] == "review-sub"
    assert "只推送影响 A 股的政策和宏观新闻。" in prompts[0][2]
    assert sent[0][0] == "webchat:FriendMessage:user"
    assert "关税政策更新" in sent[0][1]


def test_realtime_news_respects_quiet_hours(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Realtime-threshold news is queued during subscriber quiet hours."""

    config = sample_config(tmp_path, quiet_start="00:00", quiet_end="23:59")
    news_server.ensure_news_schema(config.database_path)
    monkeypatch.setattr(news_server, "subscriber_preference_features", lambda *_args: {})
    monkeypatch.setattr(
        news_server,
        "rate_news_items",
        lambda _config, items, _subscriber, _features: [
            {
                "news_id": items[0][0],
                "keep": True,
                "category": "政策监管",
                "importance": 5,
                "urgency": 4,
                "event": "Major sanction",
                "raw_response": "{}",
            }
        ],
    )
    monkeypatch.setattr(
        news_server,
        "astrbot_send_message",
        lambda *_args: (_ for _ in ()).throw(AssertionError("should not send during quiet hours")),
    )
    item = {
        "source": "test-source",
        "provider": "test",
        "title": "Major sanction",
        "summary": "Sanctions announced",
        "url": "https://example.test/sanction",
        "published_at": "2026-06-08T09:00:00",
    }

    stats = news_server.rate_and_route_news_items(
        config,
        [(1, item)],
        config.subscribers[0],
    )

    assert stats["rated"] == 1
    assert stats["queued"] == 1
    assert stats["sent"] == 0
    queue = news_server.news_queue_payload(config)
    assert queue["rows"] == 1
    assert "Major sanction" in queue["data"][0]["message"]


def test_news_once_skips_unaccepted_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A subscriber can opt out of a news source."""

    config = sample_config(tmp_path, subscriber_sources=("marketaux-market",))
    monkeypatch.setattr(
        news_server,
        "collect_source",
        lambda _source, _config=None, _token_index=0: [
            {
                "source": "gdelt-policy",
                "provider": "gdelt",
                "title": "Policy update",
                "summary": "Policy summary",
                "url": "https://example.test/news/3",
                "published_at": "2026-06-08T09:00:00",
                "fingerprint": "fingerprint-3",
                "raw_json": "{}",
            }
        ],
    )

    payload = news_server.run_news_once(config)

    assert payload["new"] == 1
    assert payload["rated"] == 0
    assert payload["skipped"] == 1


def test_source_schedule_uses_enumerated_times(tmp_path: Path) -> None:
    """Enumerated source schedules are stored as next epoch times."""

    config = sample_config(tmp_path)
    source = NewsSourceConfig(
        name="scheduled",
        type="gdelt",
        enabled=True,
        interval_seconds=300,
        schedule_times=("09:30", "15:00"),
        active_windows=(),
        limit=10,
        params={},
    )
    tz = ZoneInfo("Asia/Shanghai")
    now = int(datetime(2026, 6, 8, 10, 0, tzinfo=tz).timestamp())

    next_run = news_server.compute_next_run_at(config, source, now)

    assert next_run == int(datetime(2026, 6, 8, 15, 0, tzinfo=tz).timestamp())


def test_source_active_windows_defer_until_window(tmp_path: Path) -> None:
    """Interval schedules outside active windows move to the next window start."""

    config = sample_config(tmp_path)
    source = NewsSourceConfig(
        name="windowed",
        type="gdelt",
        enabled=True,
        interval_seconds=600,
        schedule_times=(),
        active_windows=("09:30-11:30", "13:00-15:00"),
        limit=10,
        params={},
    )
    tz = ZoneInfo("Asia/Shanghai")
    now = int(datetime(2026, 6, 8, 11, 45, tzinfo=tz).timestamp())

    next_run = news_server.compute_next_run_at(config, source, now)

    assert next_run == int(datetime(2026, 6, 8, 13, 0, tzinfo=tz).timestamp())


def test_source_active_windows_allow_interval_inside_window(tmp_path: Path) -> None:
    """Interval schedules continue normally inside active windows."""

    config = sample_config(tmp_path)
    source = NewsSourceConfig(
        name="windowed",
        type="gdelt",
        enabled=True,
        interval_seconds=600,
        schedule_times=(),
        active_windows=("09:30-11:30",),
        limit=10,
        params={},
    )
    tz = ZoneInfo("Asia/Shanghai")
    now = int(datetime(2026, 6, 8, 10, 10, tzinfo=tz).timestamp())

    next_run = news_server.compute_next_run_at(config, source, now)

    assert next_run == int(datetime(2026, 6, 8, 10, 20, tzinfo=tz).timestamp())


def test_news_server_writes_schedule_log_without_stdout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Server mode logs cycle schedules to a file instead of stdout."""

    config = sample_config(tmp_path)
    monkeypatch.setattr(
        news_server,
        "run_news_once",
        lambda _config: {"ok": True, "function": "news-once", "sources": 1, "sent": 0},
    )

    news_server.run_news_server(config, max_cycles=1)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    lines = config.log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    start = json.loads(lines[0])
    cycle = json.loads(lines[1])
    assert start["event"] == "news-server-start"
    assert cycle["event"] == "news-server-cycle"
    assert cycle["next_server_run_at_epoch"] == 0
    assert cycle["result"]["function"] == "news-once"
    assert cycle["sources"][0]["name"] == "test-source"


def test_review_news_items_splits_by_context_chars(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Large user batches are summarized before the final review prompt."""

    config = sample_config(tmp_path, max_context_chars=1000)
    subscriber = config.subscribers[0]
    items = [
        (
            index,
            {
                "source": "test-source",
                "provider": "test",
                "title": f"News {index}",
                "summary": "x" * 900,
                "url": "",
                "published_at": "",
            },
        )
        for index in range(1, 4)
    ]
    calls: list[str] = []

    def fake_chat(
        _config: AstrBotConfig,
        message: str,
        subscriber: NewsSubscriberConfig | None = None,
    ) -> str:
        assert subscriber is not None
        calls.append(message)
        if "最终推送判断" in message:
            return (
                '{"push": true, "importance": 5, "urgent": false, '
                '"markets": ["A股"], "assets": [], "message": "批量摘要推送。"}'
            )
        return "本批次有重要信息。"

    monkeypatch.setattr(news_server, "astrbot_chat", fake_chat)

    review = news_server.review_news_items(config, items, subscriber)

    assert review["push"] is True
    assert review["message"] == "批量摘要推送。"
    assert len(calls) >= 2


def test_parse_sse_payload_keeps_last_text_event() -> None:
    """AstrBot SSE may end with an empty stats event after the real text."""

    raw = "\n".join(
        (
            'data: {"type":"bot","message":[{"type":"plain","text":"{\\"push\\":true}"}]}',
            'data: {"type":"bot","message":[],"agent_stats":{"token_usage":{"output":1}}}',
        )
    )

    payload = news_server.parse_sse_payload(raw)

    assert news_server.extract_text_response(payload) == '{"push":true}'


def test_review_prompt_requires_direct_push_format(tmp_path: Path) -> None:
    """Review prompts tell the bot to format message as final push content."""

    subscriber = sample_config(tmp_path).subscribers[0]
    prompt = news_server.build_review_prompt(
        {
            "source": "test-source",
            "provider": "test",
            "title": "Market news",
            "summary": "Summary",
            "url": "",
            "published_at": "",
        },
        subscriber,
    )

    assert "message 是会被直接发送给用户的最终推送正文" in prompt
    assert "必须完成排版优化" in prompt


def test_collect_source_passes_proxy_without_api_param(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Source proxy settings are local transport config, not API params."""

    config = sample_config(tmp_path)
    source = NewsSourceConfig(
        name="gdelt-policy",
        type="gdelt",
        enabled=True,
        interval_seconds=300,
        schedule_times=(),
        active_windows=(),
        limit=10,
        params={
            "endpoint": "events",
            "query": "rates",
            "proxy_url": "http://127.0.0.1:7897",
            "tokens": ["token-a", "token-b"],
        },
    )
    captured: dict[str, object] = {}

    def fake_fetch_gdelt_news(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"data": {"events": [{"title": "one"}]}}

    monkeypatch.setattr(news_server, "fetch_gdelt_news", fake_fetch_gdelt_news)

    news_server.collect_source(source, config, token_index=1)

    assert captured["token_value"] == "token-b"
    assert captured["proxy_url"] == "http://127.0.0.1:7897"
    assert captured["params"] == {"query": "rates"}


def test_marketaux_source_adds_moving_published_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Marketaux collection defaults to a recent publication window."""

    config = sample_config(tmp_path)
    source = NewsSourceConfig(
        name="marketaux-market",
        type="marketaux",
        enabled=True,
        interval_seconds=900,
        schedule_times=(),
        active_windows=(),
        limit=3,
        params={
            "countries": "us,jp,kr",
            "search": "Federal Reserve|semiconductor|oil",
            "lookback_seconds": 7200,
            "token": "token-a",
        },
    )
    now_epoch = int(datetime(2026, 6, 11, 8, 0, tzinfo=ZoneInfo("UTC")).timestamp())
    captured: dict[str, object] = {}

    def fake_fetch_marketaux_news(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"data": {"data": [{"title": "one"}]}}

    monkeypatch.setattr(news_server.time, "time", lambda: now_epoch)
    monkeypatch.setattr(news_server, "fetch_marketaux_news", fake_fetch_marketaux_news)

    news_server.collect_source(source, config, token_index=0)

    assert captured["limit"] == 3
    assert captured["token_value"] == "token-a"
    assert captured["params"] == {
        "countries": "us,jp,kr",
        "search": "Federal Reserve|semiconductor|oil",
        "published_after": "2026-06-11T06:00:00",
    }


def test_marketaux_sections_retry_next_token_on_quota_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Marketaux quota errors move collection to the next token."""

    config = sample_config(tmp_path)
    source = NewsSourceConfig(
        name="marketaux-market",
        type="marketaux",
        enabled=True,
        interval_seconds=900,
        schedule_times=(),
        active_windows=(),
        limit=3,
        params={
            "countries": "us,jp,kr",
            "token": "token-a,token-b",
            "sections": [
                {"name": "macro", "search": "Federal Reserve|inflation"},
                {"name": "chips", "search": "semiconductor|chip"},
            ],
        },
    )
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_fetch_marketaux_news(**kwargs: object) -> dict[str, object]:
        token = str(kwargs["token_value"])
        params = dict(kwargs["params"])
        calls.append((token, params))
        if len(calls) == 1:
            raise marketaux_http_error(429, {"error": {"code": "rate_limit_reached"}})
        return {"data": {"data": [{"title": f"{token}-{params['search']}"}]}}

    monkeypatch.setattr(news_server, "fetch_marketaux_news", fake_fetch_marketaux_news)

    items = news_server.collect_source(source, config, token_index=0)

    assert [call[0] for call in calls] == ["token-a", "token-b", "token-a"]
    assert [call[1]["search"] for call in calls] == [
        "Federal Reserve|inflation",
        "Federal Reserve|inflation",
        "semiconductor|chip",
    ]
    assert [item["title"] for item in items] == [
        "token-b-Federal Reserve|inflation",
        "token-a-semiconductor|chip",
    ]
    assert news_server.source_next_token_index("marketaux-market", 0) == 3


def test_akshare_flash_supports_stable_news_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AKShare flash collection supports the stable headline providers."""

    calls: list[str] = []

    class FakeFrame:
        def head(self, limit: int) -> FakeFrame:
            assert limit == 5
            return self

        def to_json(self, *, orient: str, force_ascii: bool) -> str:
            assert orient == "records"
            assert force_ascii is False
            return json.dumps([{"标题": "headline", "内容": "body"}], ensure_ascii=False)

    def fake_function(name: str) -> Callable[[], FakeFrame]:
        def call() -> FakeFrame:
            calls.append(name)
            return FakeFrame()

        return call

    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(
            stock_info_global_em=fake_function("eastmoney"),
            stock_info_global_futu=fake_function("futu"),
            stock_info_global_sina=fake_function("sina"),
            stock_info_global_ths=fake_function("ths"),
            stock_news_main_cx=fake_function("caixin"),
        ),
    )

    for provider in ("eastmoney", "futu", "sina", "ths", "caixin"):
        source = NewsSourceConfig(
            name=f"{provider}-news",
            type="akshare_flash",
            enabled=True,
            interval_seconds=60,
            schedule_times=(),
            active_windows=(),
            limit=5,
            params={"source": provider},
        )
        items = news_server.collect_source(source)
        assert items[0]["provider"] == provider

    assert calls == ["eastmoney", "futu", "sina", "ths", "caixin"]


def test_akshare_economic_calendar_normalizes_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Baidu economic calendar rows are normalized as news events."""

    class FakeFrame:
        def head(self, limit: int) -> FakeFrame:
            assert limit == 10
            return self

        def to_json(self, *, orient: str, force_ascii: bool) -> str:
            assert orient == "records"
            assert force_ascii is False
            return json.dumps(
                [{"事件": "美国CPI公布", "日期": "2026-06-11", "时间": "20:30"}],
                ensure_ascii=False,
            )

    def fake_news_economic_baidu(*, date: str, cookie: str | None) -> FakeFrame:
        assert date == "20260611"
        assert cookie is None
        return FakeFrame()

    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(news_economic_baidu=fake_news_economic_baidu),
    )
    source = NewsSourceConfig(
        name="baidu-economic-calendar",
        type="akshare_economic_calendar",
        enabled=True,
        interval_seconds=3600,
        schedule_times=(),
        active_windows=(),
        limit=10,
        params={"date": "20260611"},
    )

    items = news_server.collect_source(source)

    assert items[0]["provider"] == "baidu-economic"
    assert items[0]["title"] == "美国CPI公布"


def marketaux_http_error(status: int, body: dict[str, object]) -> HTTPError:
    """Build a readable HTTPError for Marketaux retry tests."""

    error = HTTPError(
        url="https://api.marketaux.com/v1/news/all",
        code=status,
        msg="Too Many Requests",
        hdrs={},
        fp=BytesIO(json.dumps(body).encode()),
    )
    return error


def sample_config(
    tmp_path: Path,
    *,
    quiet_enabled: bool = True,
    quiet_start: str = "23:00",
    quiet_end: str = "08:30",
    subscriber_sources: tuple[str, ...] = (),
    subscriber_prompt: str = "",
    max_context_chars: int = 12000,
    digest_min_items: int = 10,
) -> NewsServerConfig:
    """Build a minimal news server config."""

    return NewsServerConfig(
        interval_seconds=60,
        database_path=tmp_path / "news.sqlite3",
        log_path=tmp_path / "logs" / "news_server.log",
        timezone="Asia/Shanghai",
        quiet_hours=QuietHoursConfig(
            enabled=quiet_enabled,
            start=quiet_start,
            end=quiet_end,
            flush_on_end=True,
        ),
        astrbot=AstrBotConfig(
            base_url="http://localhost:6185",
            api_key="token",
            review_username="agent",
            review_session_id="session",
            timeout=5,
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
            ),
        ),
        subscribers=(
            NewsSubscriberConfig(
                name="sub",
                umo="webchat:FriendMessage:user",
                enabled=True,
                min_importance=4,
                markets=(),
                sources=subscriber_sources,
                prompt=subscriber_prompt,
                prompt_prefix=subscriber_prompt,
                prompt_suffix="",
                news_preference=subscriber_prompt,
                min_keep_importance=2,
                realtime_min_importance=5,
                realtime_min_urgency=4,
                rating_batch_size=30,
                digest_min_items=digest_min_items,
                digest_max_items=40,
                digest_times=(),
                max_context_chars=max_context_chars,
                review_username="agent",
                review_session_id="review-sub",
                quiet_hours=QuietHoursConfig(
                    enabled=quiet_enabled,
                    start=quiet_start,
                    end=quiet_end,
                    flush_on_end=True,
                ),
            ),
        ),
    )
