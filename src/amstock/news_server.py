"""News polling server with AI rating and storage."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from datetime import time as datetime_time
from pathlib import Path
from typing import Any, cast
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from amstock.config import (
    amstock_home,
    load_config_file,
    load_settings,
    resolve_config_path,
    sqlite_path_from_url,
)
JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
_MARKETAUX_NEXT_TOKEN_INDEX: dict[str, int] = {}


@dataclass(frozen=True, slots=True)
class NewsSourceConfig:
    """One configured news source."""

    name: str
    type: str
    enabled: bool
    interval_seconds: int
    schedule_times: tuple[str, ...]
    active_windows: tuple[str, ...]
    limit: int
    params: dict[str, object]
    user_prompt: str = ""
    processor_type: str = "ai"


@dataclass(frozen=True, slots=True)
class AIConfig:
    """OpenAI-format AI provider configuration."""

    base_url: str
    api_key: str
    model: str
    timeout: float
    sys_prompt: str


@dataclass(frozen=True, slots=True)
class NewsServerConfig:
    """Runtime news server configuration."""

    interval_seconds: int
    database_path: Path
    log_path: Path
    timezone: str
    ai: AIConfig
    sources: tuple[NewsSourceConfig, ...]


def load_news_server_config() -> NewsServerConfig:
    """Load news server settings from AMSTOCK_HOME/config/config.toml."""

    home = amstock_home()
    path = resolve_config_path(home)
    config = load_config_file(path)
    settings = load_settings()
    server = mapping_at(config, "news", "server")
    ai = mapping_at(config, "news", "ai")
    configured_database_path = string_value(server, "database_path", "")
    database_path = (
        resolve_home_path(home, configured_database_path)
        if configured_database_path
        else news_database_path(settings.database_url)
    )
    log_path = resolve_home_path(home, string_value(server, "log_path", "logs/news_server.log"))
    return NewsServerConfig(
        interval_seconds=int_value(server, "interval_seconds", 300),
        database_path=database_path,
        log_path=log_path,
        timezone=string_value(server, "timezone", settings.timezone),
        ai=AIConfig(
            base_url=string_value(ai, "base_url", "https://api.openai.com/v1"),
            api_key=string_value(ai, "api_key", ""),
            model=string_value(ai, "model", "gpt-4o-mini"),
            timeout=float_value(ai, "timeout", 60.0),
            sys_prompt=string_value(ai, "sys_prompt", ""),
        ),
        sources=tuple(load_news_sources(config)),
    )


def load_news_sources(config: dict[str, Any]) -> list[NewsSourceConfig]:
    """Load configured sources, with a useful Eastmoney default."""

    news_config = config.get("news")
    raw_sources = news_config.get("sources") if isinstance(news_config, dict) else None
    if not isinstance(raw_sources, list) or not raw_sources:
        return [
            NewsSourceConfig(
                name="eastmoney-flash",
                type="akshare_flash",
                enabled=True,
                interval_seconds=180,
                schedule_times=(),
                active_windows=(),
                limit=100,
                params={"source": "eastmoney"},
                user_prompt="",
            )
        ]
    sources: list[NewsSourceConfig] = []
    for index, raw in enumerate(raw_sources):
        if not isinstance(raw, dict):
            continue
        name = string_value(raw, "name", f"source-{index + 1}")
        source_type = string_value(raw, "type", "")
        sources.append(
            NewsSourceConfig(
                name=name,
                type=source_type,
                enabled=bool_value(raw, "enabled", True),
                interval_seconds=int_value(raw, "interval_seconds", 300),
                schedule_times=tuple(
                    string_list_value(raw, "schedule_times") or string_list_value(raw, "times")
                ),
                active_windows=tuple(string_list_value(raw, "active_windows")),
                limit=int_value(raw, "limit", 20),
                params={
                    key: value
                    for key, value in raw.items()
                    if key
                    not in {
                        "name",
                        "type",
                        "enabled",
                        "interval_seconds",
                        "schedule_times",
                        "times",
                        "active_windows",
                        "limit",
                        "user_prompt",
                        "processor_type",
                    }
                },
                user_prompt=string_value(raw, "user_prompt", ""),
                processor_type=string_value(raw, "processor_type", "ai"),
            )
        )
    return sources


def run_news_once(config: NewsServerConfig | None = None) -> dict[str, object]:
    """Run one collection and rating cycle with per-source processors."""
    cfg = config or load_news_server_config()
    pipeline = _build_pipeline(cfg)
    return pipeline.run_once()


def run_news_server(
    config: NewsServerConfig | None = None,
    *,
    max_cycles: int | None = None,
) -> None:
    """Run the polling server loop with per-source processors."""
    cfg = config or load_news_server_config()
    pipeline = _build_pipeline(cfg)
    pipeline.run_server(max_cycles=max_cycles)


def write_news_server_log(config: NewsServerConfig, payload: dict[str, object]) -> None:
    """Append one structured news server log event."""

    config.log_path.parent.mkdir(parents=True, exist_ok=True)
    with config.log_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def news_server_start_log_payload(config: NewsServerConfig) -> dict[str, object]:
    """Build the server-start log event."""

    now_epoch = int(time.time())
    return {
        "event": "news-server-start",
        "at": epoch_text(now_epoch, config.timezone),
        "at_epoch": now_epoch,
        "database_path": str(config.database_path),
        "log_path": str(config.log_path),
        "server_interval_seconds": config.interval_seconds,
        "ai_model": config.ai.model,
        "ai_base_url": config.ai.base_url,
        "sources": source_schedule_snapshots(config, now_epoch),
    }


def news_server_cycle_log_payload(
    config: NewsServerConfig,
    cycle: int,
    cycle_started_at: int,
    result: dict[str, object],
    max_cycles: int | None,
) -> dict[str, object]:
    """Build one polling-cycle log event."""

    finished_at = int(time.time())
    reached_max_cycles = max_cycles is not None and cycle >= max_cycles
    next_server_run_at = 0 if reached_max_cycles else finished_at + config.interval_seconds
    next_server_run_at_text = (
        "" if next_server_run_at == 0 else epoch_text(next_server_run_at, config.timezone)
    )
    return {
        "event": "news-server-cycle",
        "cycle": cycle,
        "started_at": epoch_text(cycle_started_at, config.timezone),
        "started_at_epoch": cycle_started_at,
        "finished_at": epoch_text(finished_at, config.timezone),
        "finished_at_epoch": finished_at,
        "next_server_run_at": next_server_run_at_text,
        "next_server_run_at_epoch": next_server_run_at,
        "server_interval_seconds": config.interval_seconds,
        "result": result,
        "sources": source_schedule_snapshots(config, finished_at),
    }


def news_server_error_log_payload(
    config: NewsServerConfig,
    cycle: int,
    cycle_started_at: int,
    exc: Exception,
) -> dict[str, object]:
    """Build one polling-cycle error log event."""

    failed_at = int(time.time())
    return {
        "event": "news-server-error",
        "cycle": cycle,
        "started_at": epoch_text(cycle_started_at, config.timezone),
        "started_at_epoch": cycle_started_at,
        "failed_at": epoch_text(failed_at, config.timezone),
        "failed_at_epoch": failed_at,
        "server_interval_seconds": config.interval_seconds,
        "error": {"type": type(exc).__name__, "message": str(exc)},
        "sources": source_schedule_snapshots(config, failed_at),
    }


def source_schedule_snapshots(config: NewsServerConfig, now_epoch: int) -> list[dict[str, object]]:
    """Return configured source schedules plus persisted next-run state."""

    state = source_state_rows(config.database_path)
    rows: list[dict[str, object]] = []
    for source in config.sources:
        row = state.get(source.name, {})
        next_run_at = int_value(row, "next_run_at", 0)
        last_run_at = int_value(row, "last_run_at", 0)
        last_success_at = int_value(row, "last_success_at", 0)
        rows.append(
            {
                "name": source.name,
                "type": source.type,
                "enabled": source.enabled,
                "interval_seconds": source.interval_seconds,
                "schedule_times": list(source.schedule_times),
                "active_windows": list(source.active_windows),
                "limit": source.limit,
                "due": source.enabled and (next_run_at == 0 or next_run_at <= now_epoch),
                "next_run_at": epoch_text(next_run_at, config.timezone),
                "next_run_at_epoch": next_run_at,
                "last_run_at": epoch_text(last_run_at, config.timezone),
                "last_run_at_epoch": last_run_at,
                "last_success_at": epoch_text(last_success_at, config.timezone),
                "last_success_at_epoch": last_success_at,
                "token_index": int_value(row, "token_index", 0),
                "last_error": string_value(row, "last_error", ""),
            }
        )
    return rows


def source_state_rows(path: Path) -> dict[str, dict[str, Any]]:
    """Read persisted source schedule state."""

    if not path.exists():
        return {}
    try:
        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT
                    source_name,
                    next_run_at,
                    last_run_at,
                    last_success_at,
                    token_index,
                    last_error
                FROM news_source_state
                """
            ).fetchall()
    except sqlite3.Error:
        return {}
    return {str(row["source_name"]): dict(row) for row in rows}


def epoch_text(epoch: int, timezone: str) -> str:
    """Format an epoch timestamp in the configured timezone."""

    if epoch <= 0:
        return ""
    return datetime.fromtimestamp(epoch, ZoneInfo(timezone)).isoformat()


def source_next_token_index(source_name: str, default: int) -> int:
    """Return a collected source's next token index, if it reported one."""

    return _MARKETAUX_NEXT_TOKEN_INDEX.pop(source_name, default)


def source_token(
    source: NewsSourceConfig,
    config: NewsServerConfig | None,
    token_index: int,
) -> str | None:
    """Return the configured token for a source, rotating across available values."""

    tokens = source_tokens(source, config)
    if not tokens:
        return None
    return tokens[token_index % len(tokens)]


def source_tokens(
    source: NewsSourceConfig,
    config: NewsServerConfig | None,
) -> tuple[str, ...]:
    """Return source-specific or global tokens."""

    explicit = token_list_from_value(source.params.get("tokens")) or token_list_from_value(
        source.params.get("token")
    )
    if explicit:
        return tuple(explicit)
    try:
        settings = load_settings()
    except Exception:
        return ()
    if source.type == "gdelt":
        return settings.gdelt_cloud_tokens or (
            (settings.gdelt_cloud_token,) if settings.gdelt_cloud_token else ()
        )
    if source.type == "marketaux":
        return settings.marketaux_tokens or (
            (settings.marketaux_token,) if settings.marketaux_token else ()
        )
    return ()


def token_list_from_value(value: object) -> list[str]:
    """Normalize token config values."""

    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def source_proxy_url(source: NewsSourceConfig) -> str | None:
    """Return source-specific proxy override when configured."""

    value = source.params.get("proxy_url")
    return value.strip() if isinstance(value, str) and value.strip() else None


def api_params(source: NewsSourceConfig) -> dict[str, object]:
    """Return remote API params, excluding local AMStock source settings."""

    local_keys = {"token", "tokens", "proxy_url", "lookback_seconds", "sections"}
    return {key: value for key, value in source.params.items() if key not in local_keys}


def marketaux_api_params(
    source: NewsSourceConfig,
    config: NewsServerConfig | None,
    section_params: dict[str, object] | None = None,
) -> dict[str, object]:
    """Return Marketaux params with a default moving publication window."""

    params = {**api_params(source), **(section_params or {})}
    if any(key in params for key in ("published_after", "published_before", "published_on")):
        return params
    now_epoch = int(time.time())
    last_success_at = source_last_success_at(config.database_path, source.name) if config else 0
    if last_success_at > 0:
        start_epoch = max(0, last_success_at - 60)
    else:
        default_lookback = max(source.interval_seconds * 2, 3600)
        lookback_seconds = int_value(source.params, "lookback_seconds", default_lookback)
        start_epoch = max(0, now_epoch - max(lookback_seconds, 60))
    params["published_after"] = utc_datetime_param(start_epoch)
    return params


def source_last_success_at(path: Path, source_name: str) -> int:
    """Return the persisted successful run epoch for one source."""

    try:
        with sqlite3.connect(path) as conn:
            row = conn.execute(
                "SELECT last_success_at FROM news_source_state WHERE source_name = ?",
                (source_name,),
            ).fetchone()
    except sqlite3.Error:
        return 0
    return int(row[0]) if row else 0


def utc_datetime_param(epoch: int) -> str:
    """Format a UTC timestamp for APIs that reject explicit timezone suffixes."""

    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%dT%H:%M:%S")


def normalize_items(source_name: str, provider: str, data: object) -> list[dict[str, object]]:
    """Normalize common news payload shapes into news item dictionaries."""

    records = extract_record_list(data)
    items: list[dict[str, object]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        title = first_string(
            record,
            ("title", "标题", "新闻标题", "headline", "name", "公告标题", "事件", "tag"),
        )
        content = first_string(
            record,
            ("summary", "摘要", "description", "内容", "新闻内容", "body"),
        )
        url = first_string(record, ("url", "link", "链接", "新闻链接", "网址"))
        published_at = first_string(
            record,
            ("published_at", "published", "time", "datetime", "发布时间", "公告日期", "date"),
        )
        if not title and content:
            title = content[:80]
        if not title:
            continue
        raw = json.dumps(record, ensure_ascii=False, sort_keys=True)
        fingerprint = news_fingerprint(provider, title, url, published_at)
        items.append(
            {
                "source": source_name,
                "provider": provider,
                "title": title,
                "summary": content,
                "url": url,
                "published_at": published_at,
                "fingerprint": fingerprint,
                "raw_json": raw,
            }
        )
    return items



def rate_and_store_news_items(
    config: NewsServerConfig,
    items: list[tuple[int, dict[str, object]]],
) -> dict[str, object]:
    """Rate new items with AI and store ratings."""

    stats: dict[str, object] = {"rated": 0, "errors": []}
    if not items:
        return stats
    for batch in chunk_items(items, 30):
        try:
            ratings = rate_news_items(config, batch)
        except Exception as exc:
            cast("list[dict[str, object]]", stats["errors"]).append(
                {"error": {"type": type(exc).__name__, "message": str(exc)}}
            )
            continue
        for item_id, item in batch:
            rating = normalize_rating(
                find_rating_for_item(ratings, item_id),
                item_id,
                item,
            )
            rating["raw_response"] = json.dumps(rating, ensure_ascii=False, sort_keys=True)
            save_news_review(config.database_path, item_id, rating_to_review(rating))
            stats["rated"] = int(stats["rated"]) + 1
    return stats


def rate_news_items(
    config: NewsServerConfig,
    items: list[tuple[int, dict[str, object]]],
) -> list[dict[str, object]]:
    """Ask AI provider to classify and rate a batch of news events."""

    if not config.ai.api_key:
        return [
            fallback_rating(item_id, item, "missing ai api_key")
            for item_id, item in items
        ]
    messages = build_rating_messages(config.ai.sys_prompt, items)
    try:
        response_text = openai_chat_completion(config.ai, messages)
    except Exception:
        return [
            fallback_rating(item_id, item, "ai request failed")
            for item_id, item in items
        ]
    parsed = parse_json_object(response_text)
    raw_items: list[dict[str, object]] = []
    if isinstance(parsed, dict):
        raw = parsed.get("items") or parsed.get("ratings") or parsed.get("data")
        raw_items = raw if isinstance(raw, list) else []
    ratings = [item for item in raw_items if isinstance(item, dict)]
    if not ratings:
        return [fallback_rating(item_id, item, response_text) for item_id, item in items]
    normalized: list[dict[str, object]] = []
    for item_id, item in items:
        rating = find_rating_for_item(ratings, item_id)
        normalized.append(normalize_rating(rating, item_id, item, raw_response=response_text))
    return normalized


def openai_chat_completion(
    config: AIConfig,
    messages: list[dict[str, str]],
) -> str:
    """Send chat completion request to OpenAI-compatible endpoint."""

    payload = {
        "model": config.model,
        "messages": messages,
        "temperature": 0.1,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(
        f"{config.base_url.rstrip('/')}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "AMStock/0.1",
        },
        method="POST",
    )
    with urlopen(req, timeout=config.timeout) as response:
        raw = response.read().decode("utf-8-sig")
    data = json.loads(raw)
    choices = data.get("choices", [])
    if choices:
        return str(choices[0].get("message", {}).get("content", ""))
    return ""


def build_rating_messages(
    sys_prompt: str,
    items: list[tuple[int, dict[str, object]]],
) -> list[dict[str, str]]:
    """Build OpenAI-format messages for news rating."""

    parts = [
        format_news_part_with_id(item_id, index + 1, item)
        for index, (item_id, item) in enumerate(items)
    ]
    user_content = "以下是需要评估的新闻列表:\n\n" + "\n\n".join(parts)
    return [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_content},
    ]

def format_news_part_with_id(item_id: int, index: int, item: dict[str, object]) -> str:
    """Format one news item with its database id."""

    return f"news_id: {item_id}\n{format_news_part(index, item)}"


def format_news_part(index: int, item: dict[str, object]) -> str:
    """Format one news item for AI prompts."""

    return (
        f"[{index}]\n"
        f"标题: {item.get('title')}\n"
        f"摘要: {item.get('summary')}\n"
        f"配置源: {item.get('source')}\n"
        f"来源: {item.get('provider')}\n"
        f"时间: {item.get('published_at')}\n"
        f"链接: {item.get('url')}\n"
    )


def find_rating_for_item(
    ratings: list[dict[str, object]],
    item_id: int,
) -> dict[str, object] | None:
    """Find one rating by news id."""

    for rating in ratings:
        try:
            if int(rating.get("news_id") or rating.get("id") or 0) == item_id:
                return rating
        except (TypeError, ValueError):
            continue
    return None


def normalize_rating(
    rating: dict[str, object] | None,
    item_id: int,
    item: dict[str, object],
    *,
    raw_response: str = "",
) -> dict[str, object]:
    """Normalize an agent rating into the fields AMStock stores."""

    if rating is None:
        return fallback_rating(item_id, item, raw_response or "missing rating")
    event = str(rating.get("event") or rating.get("message") or item.get("title") or "").strip()
    return {
        "news_id": item_id,
        "keep": bool(rating.get("keep")),
        "category": str(rating.get("category") or "其他"),
        "importance": clamp_int(rating.get("importance"), 1, 5, 1),
        "urgency": clamp_int(rating.get("urgency"), 1, 5, 1),
        "event": event,
        "reason": str(rating.get("reason") or ""),
        "raw_response": raw_response,
    }


def fallback_rating(item_id: int, item: dict[str, object], raw_response: str) -> dict[str, object]:
    """Return a conservative non-keep rating when the agent cannot rate an item."""

    return {
        "news_id": item_id,
        "keep": False,
        "category": "其他",
        "importance": 1,
        "urgency": 1,
        "event": str(item.get("title") or ""),
        "reason": "rating unavailable",
        "raw_response": raw_response,
    }



def rating_to_review(rating: dict[str, object]) -> dict[str, object]:
    """Convert a rating into the review storage shape with category."""

    return {
        "push": bool(rating.get("keep")),
        "importance": int(rating.get("importance") or 0),
        "urgent": int(rating.get("urgency") or 0) >= 4,
        "category": str(rating.get("category") or "其他"),
        "markets": [],
        "assets": [],
        "message": str(rating.get("event") or ""),
        "raw_response": str(rating.get("raw_response") or ""),
    }

def chunk_items(
    items: list[tuple[int, dict[str, object]]],
    size: int,
) -> list[list[tuple[int, dict[str, object]]]]:
    """Split item tuples into fixed-size chunks."""

    return [items[index : index + size] for index in range(0, len(items), size)]


def clamp_int(value: object, minimum: int, maximum: int, default: int) -> int:
    """Parse and clamp an integer."""

    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))



def ensure_news_schema(path: Path) -> None:
    """Create the news server SQLite schema."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS news_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                provider TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                url TEXT NOT NULL,
                published_at TEXT NOT NULL,
                fingerprint TEXT NOT NULL UNIQUE,
                raw_json TEXT NOT NULL,
                first_seen_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS news_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                news_item_id INTEGER NOT NULL,
                subscriber_name TEXT NOT NULL DEFAULT '',
                review_username TEXT NOT NULL DEFAULT '',
                review_session_id TEXT NOT NULL DEFAULT '',
                push INTEGER NOT NULL,
                importance INTEGER NOT NULL,
                urgent INTEGER NOT NULL,
                markets TEXT NOT NULL,
                assets TEXT NOT NULL,
                message TEXT NOT NULL,
                raw_response TEXT NOT NULL,
                reviewed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS news_delivery_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subscriber_name TEXT NOT NULL,
                umo TEXT NOT NULL,
                news_item_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                status TEXT NOT NULL,
                error TEXT NOT NULL,
                created_at TEXT NOT NULL,
                sent_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS news_source_state (
                source_name TEXT PRIMARY KEY,
                next_run_at INTEGER NOT NULL,
                last_run_at INTEGER NOT NULL,
                last_success_at INTEGER NOT NULL,
                token_index INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS news_subscriber_preferences (
                subscriber_name TEXT PRIMARY KEY,
                preference_text TEXT NOT NULL,
                preference_features_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS news_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subscriber_name TEXT NOT NULL,
                news_item_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                importance INTEGER NOT NULL,
                urgency INTEGER NOT NULL,
                event TEXT NOT NULL,
                status TEXT NOT NULL,
                delivery_mode TEXT NOT NULL,
                rating_raw_json TEXT NOT NULL,
                queued_at TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                UNIQUE(subscriber_name, news_item_id)
            );
            """
        )
        ensure_columns(
            conn,
            "news_reviews",
            {
                "subscriber_name": "TEXT NOT NULL DEFAULT ''",
                "review_username": "TEXT NOT NULL DEFAULT ''",
                "review_session_id": "TEXT NOT NULL DEFAULT ''",
                "category": "TEXT NOT NULL DEFAULT ''",
            },
        )
        ensure_columns(
            conn,
            "news_cache",
            {
                "category": "TEXT NOT NULL DEFAULT '其他'",
                "importance": "INTEGER NOT NULL DEFAULT 0",
                "urgency": "INTEGER NOT NULL DEFAULT 0",
                "event": "TEXT NOT NULL DEFAULT ''",
                "delivery_mode": "TEXT NOT NULL DEFAULT 'digest'",
                "rating_raw_json": "TEXT NOT NULL DEFAULT ''",
                "queued_at": "TEXT NOT NULL DEFAULT ''",
                "sent_at": "TEXT NOT NULL DEFAULT ''",
            },
        )


def source_due(path: Path, source: NewsSourceConfig, now_epoch: int) -> bool:
    """Return whether a source should be collected now."""

    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT next_run_at FROM news_source_state WHERE source_name = ?",
            (source.name,),
        ).fetchone()
    return row is None or int(row[0]) <= now_epoch


def source_token_index(path: Path, source_name: str) -> int:
    """Return the persisted token index for a source."""

    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT token_index FROM news_source_state WHERE source_name = ?",
            (source_name,),
        ).fetchone()
    return int(row[0]) if row else 0


def schedule_next_source_run(
    path: Path,
    config: NewsServerConfig,
    source: NewsSourceConfig,
    now_epoch: int,
    token_index: int,
    error: str = "",
) -> None:
    """Persist the source's next collection time."""

    next_run_at = compute_next_run_at(config, source, now_epoch)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            INSERT INTO news_source_state
                (source_name, next_run_at, last_run_at, last_success_at, token_index, last_error)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_name) DO UPDATE SET
                next_run_at = excluded.next_run_at,
                last_run_at = excluded.last_run_at,
                last_success_at = excluded.last_success_at,
                token_index = excluded.token_index,
                last_error = excluded.last_error
            """,
            (
                source.name,
                next_run_at,
                now_epoch,
                0 if error else now_epoch,
                token_index,
                error,
            ),
        )


def defer_source_until_next_active(
    path: Path,
    config: NewsServerConfig,
    source: NewsSourceConfig,
    now_epoch: int,
    token_index: int,
) -> None:
    """Move a due source to its next active window without marking a run."""

    next_run_at = next_active_window_epoch(source.active_windows, config.timezone, now_epoch)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            INSERT INTO news_source_state
                (source_name, next_run_at, last_run_at, last_success_at, token_index, last_error)
            VALUES (?, ?, 0, 0, ?, '')
            ON CONFLICT(source_name) DO UPDATE SET
                next_run_at = excluded.next_run_at,
                token_index = excluded.token_index
            """,
            (source.name, next_run_at, token_index),
        )


def compute_next_run_at(
    config: NewsServerConfig,
    source: NewsSourceConfig,
    now_epoch: int,
) -> int:
    """Compute next run epoch for interval or enumerated schedules."""

    if source.schedule_times:
        candidate = next_enumerated_epoch(source.schedule_times, config.timezone, now_epoch)
    else:
        interval = max(source.interval_seconds, 1)
        candidate = ((now_epoch // interval) + 1) * interval
    return next_allowed_run_epoch(source, config.timezone, candidate)


def next_enumerated_epoch(values: tuple[str, ...], timezone: str, now_epoch: int) -> int:
    """Return the next epoch from configured daily HH:MM or absolute epoch values."""

    numeric = sorted(int(value) for value in values if str(value).strip().isdigit())
    for value in numeric:
        if value > now_epoch:
            return value
    tz = ZoneInfo(timezone)
    now = datetime.fromtimestamp(now_epoch, tz)
    candidates: list[int] = []
    for value in values:
        text = str(value).strip()
        if text.isdigit() or ":" not in text:
            continue
        hour, minute = parse_hhmm(text).hour, parse_hhmm(text).minute
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if int(candidate.timestamp()) <= now_epoch:
            candidate += timedelta(days=1)
        candidates.append(int(candidate.timestamp()))
    if candidates:
        return min(candidates)
    return now_epoch + 300


def next_allowed_run_epoch(
    source: NewsSourceConfig,
    timezone: str,
    candidate_epoch: int,
) -> int:
    """Return candidate epoch when active, otherwise next active window start."""

    if source_active_at(source, timezone, candidate_epoch):
        return candidate_epoch
    return next_active_window_epoch(source.active_windows, timezone, candidate_epoch)


def source_active_at(source: NewsSourceConfig, timezone: str, epoch: int) -> bool:
    """Return whether a source is inside its configured active windows."""

    if not source.active_windows:
        return True
    current = datetime.fromtimestamp(epoch, ZoneInfo(timezone)).time()
    current = current.replace(second=0, microsecond=0)
    for window in source.active_windows:
        start, end = parse_active_window(window)
        if start <= end and start <= current < end:
            return True
        if start > end and (current >= start or current < end):
            return True
    return False


def next_active_window_epoch(
    active_windows: tuple[str, ...],
    timezone: str,
    now_epoch: int,
) -> int:
    """Return the next active window start epoch."""

    if not active_windows:
        return now_epoch
    tz = ZoneInfo(timezone)
    now = datetime.fromtimestamp(now_epoch, tz)
    candidates: list[int] = []
    for day_offset in range(3):
        day = now + timedelta(days=day_offset)
        for window in active_windows:
            start, _end = parse_active_window(window)
            candidate = day.replace(
                hour=start.hour,
                minute=start.minute,
                second=0,
                microsecond=0,
            )
            candidate_epoch = int(candidate.timestamp())
            if candidate_epoch > now_epoch:
                candidates.append(candidate_epoch)
    if candidates:
        return min(candidates)
    return now_epoch + 300


def parse_hhmm(value: str) -> datetime_time:
    """Parse HH:MM into a time object."""

    hour, minute = value.split(":", 1)
    return datetime_time(int(hour), int(minute))


def parse_active_window(value: str) -> tuple[datetime_time, datetime_time]:
    """Parse HH:MM-HH:MM active window."""

    if "-" not in value:
        msg = f"invalid active window {value!r}; expected HH:MM-HH:MM"
        raise ValueError(msg)
    start, end = (part.strip() for part in value.split("-", 1))
    return parse_hhmm(start), parse_hhmm(end)


def insert_news_item(path: Path, item: dict[str, object]) -> int | None:
    """Insert a news item, returning None for duplicates."""

    now = datetime.now().isoformat(timespec="seconds")
    try:
        with sqlite3.connect(path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO news_items
                (
                    source, provider, title, summary, url, published_at,
                    fingerprint, raw_json, first_seen_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(item.get("source") or ""),
                    str(item.get("provider") or ""),
                    str(item.get("title") or ""),
                    str(item.get("summary") or ""),
                    str(item.get("url") or ""),
                    str(item.get("published_at") or ""),
                    str(item.get("fingerprint") or ""),
                    str(item.get("raw_json") or "{}"),
                    now,
                ),
            )
            return int(cursor.lastrowid)
    except sqlite3.IntegrityError:
        return None


def save_news_review(
    path: Path,
    item_id: int,
    review: dict[str, object],
) -> None:
    """Persist an AI review result."""

    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            INSERT INTO news_reviews
            (
                news_item_id, subscriber_name, review_username, review_session_id,
                push, importance, urgent, markets, category,
                assets, message, raw_response, reviewed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id,
                "",
                "",
                "",
                1 if review.get("push") else 0,
                int(review.get("importance") or 0),
                1 if review.get("urgent") else 0,
                json.dumps(list_value(review.get("markets")), ensure_ascii=False),
                str(review.get("category") or "其他"),
                json.dumps(list_value(review.get("assets")), ensure_ascii=False),
                str(review.get("message") or ""),
                str(review.get("raw_response") or ""),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )



def list_news_items(
    path: Path,
    *,
    limit: int = 50,
    offset: int = 0,
    source: str = "",
    provider: str = "",
    query: str = "",
    since: str = "",
    until: str = "",
    category: str = "",
    min_importance: int = 0,
    max_importance: int = 5,
    min_urgency: int = 0,
    max_urgency: int = 5,
    keep: bool | None = None,
    event: str = "",
    sort_by: str = "first_seen_at",
    sort_order: str = "desc",
) -> list[sqlite3.Row]:
    """Query stored news items with rich filters."""

    clauses: list[str] = []
    params: list[object] = []
    if source:
        clauses.append("n.source = ?")
        params.append(source)
    if provider:
        clauses.append("n.provider = ?")
        params.append(provider)
    if query:
        like = f"%{query}%"
        clauses.append("(n.title LIKE ? OR n.summary LIKE ?)")
        params.extend((like, like))
    if since:
        clauses.append("(n.first_seen_at >= ? OR n.published_at >= ?)")
        params.extend((since, since))
    if until:
        clauses.append("(n.first_seen_at <= ? OR n.published_at <= ?)")
        params.extend((until, until))
    if category:
        clauses.append(
            """EXISTS (
                SELECT 1 FROM news_reviews r
                WHERE r.news_item_id = n.id AND r.category = ?
            )"""
        )
        params.append(category)
    if min_importance > 1 or max_importance < 5:
        clauses.append(
            """EXISTS (
                SELECT 1 FROM news_reviews r
                WHERE r.news_item_id = n.id
                  AND r.importance >= ? AND r.importance <= ?
            )"""
        )
        params.extend((min_importance, max_importance))
    if min_urgency > 1 or max_urgency < 5:
        clauses.append(
            """EXISTS (
                SELECT 1 FROM news_reviews r
                WHERE r.news_item_id = n.id
                  AND r.urgent >= ? AND r.urgent <= ?
            )"""
        )
        params.extend((1 if min_urgency >= 4 else 0, 1 if max_urgency >= 4 else 0))
    if keep is not None:
        clauses.append(
            """EXISTS (
                SELECT 1 FROM news_reviews r
                WHERE r.news_item_id = n.id AND r.push = ?
            )"""
        )
        params.append(1 if keep else 0)
    if event:
        clauses.append(
            """EXISTS (
                SELECT 1 FROM news_reviews r
                WHERE r.news_item_id = n.id AND r.message LIKE ?
            )"""
        )
        params.append(f"%{event}%")

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    # Validate sort
    allowed_sorts = {"first_seen_at", "published_at", "importance", "urgency"}
    sort_col = sort_by if sort_by in allowed_sorts else "first_seen_at"
    sort_dir = "DESC" if sort_order.lower() == "desc" else "ASC"

    # For importance/urgency sorts, join with review table
    if sort_col in ("importance", "urgency"):
        order_clause = f"""ORDER BY COALESCE(
            (SELECT r.{sort_col} FROM news_reviews r
             WHERE r.news_item_id = n.id ORDER BY r.id DESC LIMIT 1),
            0
        ) {sort_dir}"""
    else:
        order_clause = f"ORDER BY n.{sort_col} {sort_dir}"

    params.extend((max(limit, 1), max(offset, 0)))
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT
                n.id, n.source, n.provider, n.title, n.summary, n.url,
                n.published_at, n.fingerprint, n.first_seen_at,
                (
                    SELECT r.push FROM news_reviews r
                    WHERE r.news_item_id = n.id
                    ORDER BY r.id DESC LIMIT 1
                ) AS review_push,
                (
                    SELECT r.importance FROM news_reviews r
                    WHERE r.news_item_id = n.id
                    ORDER BY r.id DESC LIMIT 1
                ) AS review_importance,
                (
                    SELECT r.urgent FROM news_reviews r
                    WHERE r.news_item_id = n.id
                    ORDER BY r.id DESC LIMIT 1
                ) AS review_urgent,
                (
                    SELECT r.category FROM news_reviews r
                    WHERE r.news_item_id = n.id
                    ORDER BY r.id DESC LIMIT 1
                ) AS review_category,
                (
                    SELECT r.message FROM news_reviews r
                    WHERE r.news_item_id = n.id
                    ORDER BY r.id DESC LIMIT 1
                ) AS review_message,
                (
                    SELECT r.markets FROM news_reviews r
                    WHERE r.news_item_id = n.id
                    ORDER BY r.id DESC LIMIT 1
                ) AS review_markets,
                (
                    SELECT r.assets FROM news_reviews r
                    WHERE r.news_item_id = n.id
                    ORDER BY r.id DESC LIMIT 1
                ) AS review_assets
            FROM news_items n
            {where}
            {order_clause}
            LIMIT ? OFFSET ?
            """,
            params,
        ).fetchall()
    return list(rows)


def count_news_items(
    path: Path,
    *,
    source: str = "",
    provider: str = "",
    query: str = "",
    since: str = "",
    until: str = "",
    category: str = "",
    min_importance: int = 0,
    max_importance: int = 5,
    keep: bool | None = None,
) -> int:
    """Count news items matching filters (for pagination total)."""

    clauses: list[str] = []
    params: list[object] = []
    if source:
        clauses.append("n.source = ?")
        params.append(source)
    if provider:
        clauses.append("n.provider = ?")
        params.append(provider)
    if query:
        like = f"%{query}%"
        clauses.append("(n.title LIKE ? OR n.summary LIKE ?)")
        params.extend((like, like))
    if since:
        clauses.append("(n.first_seen_at >= ? OR n.published_at >= ?)")
        params.extend((since, since))
    if until:
        clauses.append("(n.first_seen_at <= ? OR n.published_at <= ?)")
        params.extend((until, until))
    if category:
        clauses.append(
            """EXISTS (
                SELECT 1 FROM news_reviews r
                WHERE r.news_item_id = n.id AND r.category = ?
            )"""
        )
        params.append(category)
    if min_importance > 1 or max_importance < 5:
        clauses.append(
            """EXISTS (
                SELECT 1 FROM news_reviews r
                WHERE r.news_item_id = n.id
                  AND r.importance >= ? AND r.importance <= ?
            )"""
        )
        params.extend((min_importance, max_importance))
    if keep is not None:
        clauses.append(
            """EXISTS (
                SELECT 1 FROM news_reviews r
                WHERE r.news_item_id = n.id AND r.push = ?
            )"""
        )
        params.append(1 if keep else 0)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM news_items n {where}",
            params,
        ).fetchone()
    return int(row[0]) if row else 0


def news_list_payload(
    config: NewsServerConfig | None = None,
    *,
    limit: int = 50,
    offset: int = 0,
    source: str = "",
    provider: str = "",
    query: str = "",
    since: str = "",
    until: str = "",
    category: str = "",
    min_importance: int = 1,
    max_importance: int = 5,
    min_urgency: int = 1,
    max_urgency: int = 5,
    keep: str | bool | None = None,
    event: str = "",
    sort_by: str = "first_seen_at",
    sort_order: str = "desc",
) -> dict[str, object]:
    """Return stored news items matching filters — JSON payload."""

    cfg = config or load_news_server_config()
    ensure_news_schema(cfg.database_path)
    parsed_keep = optional_bool(keep) if isinstance(keep, str) or keep is None else keep
    total = count_news_items(
        cfg.database_path,
        source=source,
        provider=provider,
        query=query,
        since=since,
        until=until,
        category=category,
        min_importance=min_importance,
        max_importance=max_importance,
        keep=parsed_keep,
    )
    rows = list_news_items(
        cfg.database_path,
        limit=limit,
        offset=offset,
        source=source,
        provider=provider,
        query=query,
        since=since,
        until=until,
        category=category,
        min_importance=min_importance,
        max_importance=max_importance,
        min_urgency=min_urgency,
        max_urgency=max_urgency,
        keep=parsed_keep,
        event=event,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    data = [news_list_row_payload(row) for row in rows]
    return {
        "ok": True,
        "function": "news-list",
        "total": total,
        "limit": limit,
        "offset": offset,
        "returned_rows": len(data),
        "data": data,
    }


def news_list_row_payload(row: sqlite3.Row) -> dict[str, object]:
    """Convert a news list query row to JSON payload."""

    review_importance = row["review_importance"]
    review_urgent = row["review_urgent"]
    rating = None
    if review_importance is not None:
        rating = {
            "push": bool(row["review_push"]),
            "importance": int(review_importance or 0),
            "urgency": (int(review_urgent or 0) >= 4),
            "category": str(row["review_category"] or ""),
            "message": str(row["review_message"] or ""),
            "markets": _parse_json_list(row["review_markets"]),
            "assets": _parse_json_list(row["review_assets"]),
        }
    return {
        "id": int(row["id"]),
        "source": str(row["source"]),
        "provider": str(row["provider"]),
        "title": str(row["title"]),
        "summary": str(row["summary"]),
        "url": str(row["url"]),
        "published_at": str(row["published_at"]),
        "first_seen_at": str(row["first_seen_at"]),
        "fingerprint": str(row["fingerprint"]),
        "rating": rating,
    }


def _parse_json_list(value: str | None) -> list[object]:
    """Parse a JSON array stored as text, returning an empty list on failure."""

    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def optional_bool(value: str | bool | None) -> bool | None:
    """Parse optional true/false filter values."""

    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    msg = f"invalid boolean value: {value}"
    raise ValueError(msg)



def ensure_columns(
    conn: sqlite3.Connection,
    table: str,
    columns: dict[str, str],
) -> None:
    """Add missing columns to an existing SQLite table."""

    existing = {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")



def extract_record_list(data: object) -> list[object]:
    """Extract a list of records from common API response shapes."""

    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("data", "events", "stories", "clusters", "results"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


def first_string(record: dict[str, object], keys: tuple[str, ...]) -> str:
    """Return the first non-empty string field from a record."""

    for key in keys:
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if value is not None and not isinstance(value, (dict, list)):
            return str(value).strip()
    return ""


def news_fingerprint(provider: str, title: str, url: str, published_at: str) -> str:
    """Build a stable news fingerprint."""

    raw = "\n".join((provider, url or title, published_at))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parse_sse_payload(raw: str) -> JsonValue:
    """Parse the last JSON data line from an SSE response."""

    last: JsonValue = {"text": raw}
    last_with_text: JsonValue | None = None
    for line in raw.splitlines():
        if not line.startswith("data:"):
            continue
        text = line.removeprefix("data:").strip()
        if not text or text == "[DONE]":
            continue
        try:
            last = cast("JsonValue", json.loads(text))
        except json.JSONDecodeError:
            last = {"text": text}
        if extract_text_response(last):
            last_with_text = last
    return last_with_text if last_with_text is not None else last


def extract_text_response(data: JsonValue) -> str:
    """Extract a text response from common AstrBot response shapes."""

    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        for key in ("text", "message", "content", "response", "data"):
            value = data.get(key)
            if isinstance(value, str):
                return value
            if isinstance(value, dict | list):
                nested = extract_text_response(cast("JsonValue", value))
                if nested:
                    return nested
    if isinstance(data, list):
        parts = (extract_text_response(cast("JsonValue", item)) for item in data)
        return "\n".join(filter(None, parts))
    return ""


def parse_json_object(text: str) -> dict[str, object] | None:
    """Parse the first JSON object from text."""

    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match is None:
            return None
        try:
            value = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return value if isinstance(value, dict) else None


def list_value(value: object) -> list[object]:
    """Normalize a scalar/list into a list."""

    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def mapping_at(config: dict[str, Any], *keys: str) -> dict[str, Any]:
    """Return a nested mapping."""

    current: object = config
    for key in keys:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    return current if isinstance(current, dict) else {}


def string_value(mapping: dict[str, Any], key: str, default: str) -> str:
    """Read a string setting."""

    value = mapping.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else default


def int_value(mapping: dict[str, Any], key: str, default: int) -> int:
    """Read an integer setting."""

    value = mapping.get(key)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return default


def float_value(mapping: dict[str, Any], key: str, default: float) -> float:
    """Read a float setting."""

    value = mapping.get(key)
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return default
    return default


def bool_value(mapping: dict[str, Any], key: str, default: bool) -> bool:
    """Read a boolean setting."""

    value = mapping.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def string_list_value(mapping: dict[str, Any], key: str) -> list[str]:
    """Read a string list setting."""

    value = mapping.get(key)
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def news_database_path(database_url: str) -> Path:
    """Resolve the news storage path from the shared app database URL."""

    path = sqlite_path_from_url(database_url)
    if path is None:
        msg = "news server requires a filesystem-backed SQLite database"
        raise ValueError(msg)
    return path


def slug_value(value: str) -> str:
    """Build a stable identifier for default per-subscriber review sessions."""

    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-")
    return slug or "subscriber"


def resolve_home_path(home: Path, value: str) -> Path:
    """Resolve a path relative to AMSTOCK_HOME."""

    path = Path(value).expanduser()
    return path if path.is_absolute() else home / path


# ---------------------------------------------------------------------------
# Pipeline integration (lazy import to avoid circular deps at module init)
# ---------------------------------------------------------------------------


def _build_pipeline(config: NewsServerConfig = None) -> object:  # type: ignore[assignment]
    """Build a ``NewsPipeline`` wired with per-source processors."""
    from amstock.news.pipeline import build_pipeline as _build

    return _build(config)


# ---------------------------------------------------------------------------
# Backward-compatible collect_source — delegates to the collector registry
# ---------------------------------------------------------------------------


def _lazy_collect_source(
    source: NewsSourceConfig,
    config: NewsServerConfig | None = None,
    token_index: int = 0,
) -> list[dict[str, object]]:
    """Collect items via the collector registry (backward-compatible wrapper)."""
    from amstock.news.collectors import collect_source as _collect_source

    return _collect_source(source, config, token_index)


collect_source = _lazy_collect_source
