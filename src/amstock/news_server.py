"""News polling server with AstrBot review and push delivery."""

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
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from amstock.config import (
    amstock_home,
    load_config_file,
    load_settings,
    resolve_config_path,
    sqlite_path_from_url,
)
from amstock.news_io import (
    DEFAULT_NEWS_TIMEOUT_SECONDS,
    fetch_gdelt_news,
    fetch_marketaux_news,
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


@dataclass(frozen=True, slots=True)
class NewsSubscriberConfig:
    """One AstrBot proactive message target."""

    name: str
    umo: str
    enabled: bool
    min_importance: int
    markets: tuple[str, ...]
    sources: tuple[str, ...]
    prompt: str
    prompt_prefix: str
    prompt_suffix: str
    news_preference: str
    min_keep_importance: int
    realtime_min_importance: int
    realtime_min_urgency: int
    rating_batch_size: int
    digest_min_items: int
    digest_max_items: int
    digest_times: tuple[str, ...]
    max_context_chars: int
    review_username: str
    review_session_id: str
    quiet_hours: QuietHoursConfig


@dataclass(frozen=True, slots=True)
class AstrBotConfig:
    """AstrBot API configuration."""

    base_url: str
    api_key: str
    review_username: str
    review_session_id: str
    timeout: float


@dataclass(frozen=True, slots=True)
class QuietHoursConfig:
    """Quiet-hours delivery policy."""

    enabled: bool
    start: str
    end: str
    flush_on_end: bool


@dataclass(frozen=True, slots=True)
class NewsServerConfig:
    """Runtime news server configuration."""

    interval_seconds: int
    database_path: Path
    log_path: Path
    timezone: str
    quiet_hours: QuietHoursConfig
    astrbot: AstrBotConfig
    sources: tuple[NewsSourceConfig, ...]
    subscribers: tuple[NewsSubscriberConfig, ...]


def load_news_server_config() -> NewsServerConfig:
    """Load news server settings from AMSTOCK_HOME/config/config.toml."""

    home = amstock_home()
    path = resolve_config_path(home)
    config = load_config_file(path)
    settings = load_settings()
    server = mapping_at(config, "news", "server")
    quiet = mapping_at(config, "news", "quiet_hours")
    astrbot = mapping_at(config, "astrbot")
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
        quiet_hours=QuietHoursConfig(
            enabled=bool_value(quiet, "enabled", True),
            start=string_value(quiet, "start", "23:00"),
            end=string_value(quiet, "end", "08:30"),
            flush_on_end=bool_value(quiet, "flush_on_end", True),
        ),
        astrbot=AstrBotConfig(
            base_url=string_value(astrbot, "base_url", "http://localhost:6185"),
            api_key=string_value(astrbot, "api_key", ""),
            review_username=string_value(astrbot, "review_username", "amstock-news-agent"),
            review_session_id=string_value(astrbot, "review_session_id", "amstock-news-review"),
            timeout=float_value(astrbot, "timeout", DEFAULT_NEWS_TIMEOUT_SECONDS),
        ),
        sources=tuple(load_news_sources(config)),
        subscribers=tuple(load_news_subscribers(config)),
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
                    }
                },
            )
        )
    return sources


def load_news_subscribers(config: dict[str, Any]) -> list[NewsSubscriberConfig]:
    """Load AstrBot subscribers."""

    astrbot_config = config.get("astrbot")
    raw = astrbot_config.get("subscribers") if isinstance(astrbot_config, dict) else None
    if not isinstance(raw, list):
        return []
    default_username = string_value(astrbot_config, "review_username", "amstock-news-agent")
    default_session_id = string_value(astrbot_config, "review_session_id", "amstock-news-review")
    global_quiet = mapping_at(config, "news", "quiet_hours")
    subscribers: list[NewsSubscriberConfig] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        umo = string_value(item, "umo", "")
        if not umo:
            continue
        name = string_value(item, "name", f"subscriber-{index + 1}")
        quiet = subscriber_quiet_hours(item, global_quiet)
        prompt_prefix = string_value(
            item,
            "prompt_prefix",
            string_value(item, "prompt", string_value(item, "review_prompt", "")),
        )
        subscribers.append(
            NewsSubscriberConfig(
                name=name,
                umo=umo,
                enabled=bool_value(item, "enabled", True),
                min_importance=int_value(item, "min_importance", 4),
                markets=tuple(string_list_value(item, "markets")),
                sources=tuple(string_list_value(item, "sources")),
                prompt=string_value(item, "prompt", string_value(item, "review_prompt", "")),
                prompt_prefix=prompt_prefix,
                prompt_suffix=string_value(item, "prompt_suffix", ""),
                news_preference=string_value(item, "news_preference", prompt_prefix),
                min_keep_importance=int_value(item, "min_keep_importance", 2),
                realtime_min_importance=int_value(item, "realtime_min_importance", 5),
                realtime_min_urgency=int_value(item, "realtime_min_urgency", 4),
                rating_batch_size=int_value(item, "rating_batch_size", 30),
                digest_min_items=int_value(item, "digest_min_items", 10),
                digest_max_items=int_value(item, "digest_max_items", 40),
                digest_times=tuple(string_list_value(item, "digest_times")),
                max_context_chars=int_value(item, "max_context_chars", 12000),
                review_username=string_value(item, "review_username", default_username),
                review_session_id=string_value(
                    item,
                    "review_session_id",
                    f"{default_session_id}-{slug_value(name)}",
                ),
                quiet_hours=quiet,
            )
        )
    return subscribers


def subscriber_list_payload(config: NewsServerConfig | None = None) -> dict[str, object]:
    """Return configured news subscribers."""

    cfg = config or load_news_server_config()
    data = [
        {
            "name": subscriber.name,
            "umo": subscriber.umo,
            "enabled": subscriber.enabled,
            "min_importance": subscriber.min_importance,
            "markets": list(subscriber.markets),
            "sources": list(subscriber.sources),
            "news_preference": subscriber.news_preference,
            "min_keep_importance": subscriber.min_keep_importance,
            "realtime_min_importance": subscriber.realtime_min_importance,
            "realtime_min_urgency": subscriber.realtime_min_urgency,
            "rating_batch_size": subscriber.rating_batch_size,
            "digest_min_items": subscriber.digest_min_items,
            "digest_max_items": subscriber.digest_max_items,
            "digest_times": list(subscriber.digest_times),
            "review_username": subscriber.review_username,
            "review_session_id": subscriber.review_session_id,
            "max_context_chars": subscriber.max_context_chars,
            "quiet_hours": {
                "enabled": subscriber.quiet_hours.enabled,
                "start": subscriber.quiet_hours.start,
                "end": subscriber.quiet_hours.end,
                "flush_on_end": subscriber.quiet_hours.flush_on_end,
            },
        }
        for subscriber in cfg.subscribers
    ]
    return {
        "ok": True,
        "function": "news-subscriber-list",
        "rows": len(data),
        "data": data,
    }


def subscriber_quiet_hours(
    item: dict[str, Any],
    global_quiet: dict[str, Any],
) -> QuietHoursConfig:
    """Load per-subscriber quiet hours with backwards-compatible flat keys."""

    nested = item.get("quiet_hours")
    quiet = nested if isinstance(nested, dict) else {}
    return QuietHoursConfig(
        enabled=bool_value(
            quiet,
            "enabled",
            bool_value(item, "quiet_hours_enabled", bool_value(global_quiet, "enabled", True)),
        ),
        start=string_value(
            quiet,
            "start",
            string_value(item, "quiet_hours_start", string_value(global_quiet, "start", "23:00")),
        ),
        end=string_value(
            quiet,
            "end",
            string_value(item, "quiet_hours_end", string_value(global_quiet, "end", "08:30")),
        ),
        flush_on_end=bool_value(
            quiet,
            "flush_on_end",
            bool_value(global_quiet, "flush_on_end", True),
        ),
    )


def run_news_once(config: NewsServerConfig | None = None) -> dict[str, object]:
    """Run one collection/review/delivery cycle."""

    cfg = config or load_news_server_config()
    ensure_news_schema(cfg.database_path)
    stats = {
        "sources": 0,
        "fetched": 0,
        "new": 0,
        "rated": 0,
        "queued": 0,
        "sent": 0,
        "skipped": 0,
        "cached": 0,
        "discarded": 0,
        "digest_sent": 0,
        "errors": [],
    }
    flush_result = flush_news_queue(cfg, respect_flush_policy=True)
    stats["sent"] = int(stats["sent"]) + int(flush_result.get("sent", 0))
    accepted_by_subscriber: dict[str, list[tuple[int, dict[str, object]]]] = {
        subscriber.name: [] for subscriber in cfg.subscribers if subscriber.enabled
    }
    now_epoch = int(time.time())
    for source in cfg.sources:
        if not source.enabled:
            continue
        if not source_due(cfg.database_path, source, now_epoch):
            continue
        token_index = source_token_index(cfg.database_path, source.name)
        if not source_active_at(source, cfg.timezone, now_epoch):
            defer_source_until_next_active(
                cfg.database_path,
                cfg,
                source,
                now_epoch,
                token_index,
            )
            continue
        stats["sources"] = int(stats["sources"]) + 1
        try:
            items = collect_source(source, cfg, token_index)
        except Exception as exc:
            cast("list[dict[str, object]]", stats["errors"]).append(
                {"source": source.name, "error": {"type": type(exc).__name__, "message": str(exc)}}
            )
            schedule_next_source_run(
                cfg.database_path,
                cfg,
                source,
                now_epoch,
                source_next_token_index(source.name, token_index + 1),
                f"{type(exc).__name__}: {exc}",
            )
            continue
        schedule_next_source_run(
            cfg.database_path,
            cfg,
            source,
            now_epoch,
            source_next_token_index(source.name, token_index + 1),
        )
        stats["fetched"] = int(stats["fetched"]) + len(items)
        for item in items:
            item_id = insert_news_item(cfg.database_path, item)
            if item_id is None:
                continue
            stats["new"] = int(stats["new"]) + 1
            for subscriber in cfg.subscribers:
                if not subscriber.enabled or not subscriber_accepts_source(subscriber, item):
                    stats["skipped"] = int(stats["skipped"]) + 1
                    continue
                accepted_by_subscriber.setdefault(subscriber.name, []).append((item_id, item))
    for subscriber in cfg.subscribers:
        accepted = accepted_by_subscriber.get(subscriber.name, [])
        if not accepted:
            continue
        result = rate_and_route_news_items(cfg, accepted, subscriber)
        for key in ("rated", "queued", "sent", "skipped", "cached", "discarded"):
            stats[key] = int(stats[key]) + int(result.get(key, 0))
    digest_result = flush_digest_cache(cfg)
    for key in ("queued", "sent", "skipped"):
        stats[key] = int(stats[key]) + int(digest_result.get(key, 0))
    stats["digest_sent"] = int(digest_result.get("sent", 0)) + int(digest_result.get("queued", 0))
    return {"ok": True, "function": "news-once", **stats}


def run_news_server(
    config: NewsServerConfig | None = None,
    *,
    max_cycles: int | None = None,
) -> None:
    """Run the polling server loop."""

    cfg = config or load_news_server_config()
    cycles = 0
    write_news_server_log(cfg, news_server_start_log_payload(cfg))
    while True:
        cycle_started_at = int(time.time())
        try:
            payload = run_news_once(cfg)
        except Exception as exc:
            write_news_server_log(
                cfg,
                news_server_error_log_payload(cfg, cycles + 1, cycle_started_at, exc),
            )
            raise
        cycles += 1
        write_news_server_log(
            cfg,
            news_server_cycle_log_payload(cfg, cycles, cycle_started_at, payload, max_cycles),
        )
        if max_cycles is not None and cycles >= max_cycles:
            return
        time.sleep(cfg.interval_seconds)


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
        "sources": source_schedule_snapshots(config, now_epoch),
        "subscribers": [
            {
                "name": subscriber.name,
                "enabled": subscriber.enabled,
                "sources": list(subscriber.sources),
                "quiet_hours": {
                    "enabled": subscriber.quiet_hours.enabled,
                    "start": subscriber.quiet_hours.start,
                    "end": subscriber.quiet_hours.end,
                    "flush_on_end": subscriber.quiet_hours.flush_on_end,
                },
            }
            for subscriber in config.subscribers
        ],
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


def collect_source(
    source: NewsSourceConfig,
    config: NewsServerConfig | None = None,
    token_index: int = 0,
) -> list[dict[str, object]]:
    """Collect normalized items from one source."""

    if source.type == "gdelt":
        params = api_params(source)
        endpoint = str(params.pop("endpoint", "events"))
        payload = fetch_gdelt_news(
            endpoint=endpoint,
            params=params,
            token_value=source_token(source, config, token_index),
            proxy_url=source_proxy_url(source),
            limit=source.limit,
        )
        return normalize_items(source.name, "gdelt", payload.get("data"))
    if source.type == "marketaux":
        return collect_marketaux_source(source, config, token_index)
    if source.type == "akshare_flash":
        return collect_akshare_flash(source)
    if source.type == "akshare_economic_calendar":
        return collect_akshare_economic_calendar(source)
    if source.type == "akshare_stock":
        return collect_akshare_stock_news(source)
    if source.type == "akshare_notice":
        return collect_akshare_notice(source)
    msg = f"unsupported news source type {source.type!r}"
    raise ValueError(msg)


def collect_akshare_flash(source: NewsSourceConfig) -> list[dict[str, object]]:
    """Collect flash or headline news through AKShare."""

    import akshare as ak

    provider = str(source.params.get("source") or "eastmoney")
    function = {
        "eastmoney": "stock_info_global_em",
        "futu": "stock_info_global_futu",
        "sina": "stock_info_global_sina",
        "ths": "stock_info_global_ths",
        "caixin": "stock_news_main_cx",
    }.get(provider)
    if function is None:
        msg = "akshare_flash source must be eastmoney, futu, sina, ths, or caixin"
        raise ValueError(msg)
    dataframe = getattr(ak, function)()
    records = json.loads(dataframe.head(source.limit).to_json(orient="records", force_ascii=False))
    return normalize_items(source.name, provider, records)


def collect_akshare_economic_calendar(source: NewsSourceConfig) -> list[dict[str, object]]:
    """Collect macroeconomic calendar events through AKShare/Baidu."""

    import akshare as ak

    date = str(source.params.get("date") or datetime.now().strftime("%Y%m%d"))
    cookie = source.params.get("cookie")
    dataframe = ak.news_economic_baidu(
        date=date,
        cookie=str(cookie) if cookie else None,
    )
    records = json.loads(dataframe.head(source.limit).to_json(orient="records", force_ascii=False))
    return normalize_items(source.name, "baidu-economic", records)


def collect_akshare_stock_news(source: NewsSourceConfig) -> list[dict[str, object]]:
    """Collect Eastmoney individual stock news through AKShare."""

    import akshare as ak

    symbol = str(source.params.get("symbol") or "")
    if not symbol:
        raise ValueError("akshare_stock source requires symbol")
    dataframe = ak.stock_news_em(symbol=symbol)
    records = json.loads(dataframe.head(source.limit).to_json(orient="records", force_ascii=False))
    return normalize_items(source.name, "eastmoney-stock", records)


def collect_akshare_notice(source: NewsSourceConfig) -> list[dict[str, object]]:
    """Collect Eastmoney A-share notices through AKShare."""

    import akshare as ak

    kind = str(source.params.get("kind") or source.params.get("symbol") or "重大事项")
    date = str(source.params.get("date") or datetime.now().strftime("%Y%m%d"))
    dataframe = ak.stock_notice_report(symbol=kind, date=date)
    records = json.loads(dataframe.head(source.limit).to_json(orient="records", force_ascii=False))
    return normalize_items(source.name, "eastmoney-notice", records)


def collect_marketaux_source(
    source: NewsSourceConfig,
    config: NewsServerConfig | None,
    token_index: int,
) -> list[dict[str, object]]:
    """Collect Marketaux news across configured topic sections."""

    tokens = source_tokens(source, config)
    sections = marketaux_sections(source)
    collected: list[dict[str, object]] = []
    current_token_index = token_index
    section_errors: list[str] = []
    for section_name, section_params in sections:
        section_items, current_token_index, error = collect_marketaux_section(
            source,
            config,
            section_name,
            section_params,
            tokens,
            current_token_index,
        )
        if error:
            section_errors.append(error)
            continue
        collected.extend(section_items)
    _MARKETAUX_NEXT_TOKEN_INDEX[source.name] = current_token_index
    if not collected and section_errors:
        raise RuntimeError("; ".join(section_errors))
    return collected


def source_next_token_index(source_name: str, default: int) -> int:
    """Return a collected source's next token index, if it reported one."""

    return _MARKETAUX_NEXT_TOKEN_INDEX.pop(source_name, default)


def collect_marketaux_section(
    source: NewsSourceConfig,
    config: NewsServerConfig | None,
    section_name: str,
    section_params: dict[str, object],
    tokens: tuple[str, ...],
    token_index: int,
) -> tuple[list[dict[str, object]], int, str]:
    """Collect one Marketaux section, trying the next token on quota errors."""

    attempts = max(len(tokens), 1)
    last_error = ""
    for attempt in range(attempts):
        effective_token_index = token_index + attempt
        token = tokens[effective_token_index % len(tokens)] if tokens else None
        try:
            payload = fetch_marketaux_news(
                params=marketaux_api_params(source, config, section_params),
                token_value=token,
                proxy_url=source_proxy_url(source),
                limit=source.limit,
            )
        except HTTPError as exc:
            error_text = marketaux_http_error_text(exc)
            last_error = f"{section_name}: HTTPError {exc.code}: {error_text}"
            if marketaux_token_exhausted_error(exc, error_text):
                continue
            return [], effective_token_index + 1, last_error
        except Exception as exc:
            last_error = f"{section_name}: {type(exc).__name__}: {exc}"
            return [], effective_token_index + 1, last_error
        items = normalize_items(source.name, "marketaux", payload.get("data"))
        return items, effective_token_index + 1, ""
    return [], token_index + attempts, last_error or f"{section_name}: all Marketaux tokens failed"


def marketaux_sections(source: NewsSourceConfig) -> list[tuple[str, dict[str, object]]]:
    """Return Marketaux request sections, falling back to the source params."""

    value = source.params.get("sections")
    if not isinstance(value, list):
        return [(source.name, {})]
    sections: list[tuple[str, dict[str, object]]] = []
    for index, raw in enumerate(value, 1):
        if not isinstance(raw, dict):
            continue
        params = {str(key): item for key, item in raw.items() if key != "name"}
        name = string_value(raw, "name", f"{source.name}-{index}")
        sections.append((name, params))
    return sections or [(source.name, {})]


def marketaux_http_error_text(exc: HTTPError) -> str:
    """Read and normalize a Marketaux HTTP error body."""

    try:
        raw = exc.read().decode("utf-8-sig", errors="replace")
    except Exception:
        return str(exc)
    if not raw:
        return str(exc)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw[:500]
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def marketaux_token_exhausted_error(exc: HTTPError, body: str) -> bool:
    """Return whether a Marketaux error should move this token behind others."""

    lowered = body.lower()
    if exc.code == 429:
        return True
    return any(
        marker in lowered
        for marker in (
            "usage_limit_reached",
            "rate_limit_reached",
            "limit reached",
            "quota",
            "too many requests",
        )
    )


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


def rate_and_route_news_items(
    config: NewsServerConfig,
    items: list[tuple[int, dict[str, object]]],
    subscriber: NewsSubscriberConfig,
) -> dict[str, int]:
    """Batch-rate new items and route them to realtime push, digest cache, or discard."""

    stats = {"rated": 0, "queued": 0, "sent": 0, "skipped": 0, "cached": 0, "discarded": 0}
    preference_features = subscriber_preference_features(config, subscriber)
    for batch in chunk_items(items, max(subscriber.rating_batch_size, 1)):
        ratings = rate_news_items(config, batch, subscriber, preference_features)
        by_id = {int(rating.get("news_id") or 0): rating for rating in ratings}
        for item_id, item in batch:
            rating = normalize_rating(by_id.get(item_id), item_id, item)
            rating["raw_response"] = json.dumps(rating, ensure_ascii=False, sort_keys=True)
            stats["rated"] += 1
            save_news_review(config.database_path, item_id, rating_to_review(rating), subscriber)
            route = route_rating(subscriber, rating)
            if route == "discard":
                upsert_news_cache(
                    config.database_path,
                    subscriber,
                    item_id,
                    rating,
                    "discarded",
                    "discard",
                )
                stats["discarded"] += 1
                continue
            if route == "realtime":
                message = format_realtime_message(item, rating)
                delivery = deliver_message(config, subscriber, item_id, message)
                upsert_news_cache(
                    config.database_path,
                    subscriber,
                    item_id,
                    rating,
                    "sent",
                    "realtime",
                )
                for key in ("queued", "sent", "skipped"):
                    stats[key] += int(delivery.get(key, 0))
                continue
            upsert_news_cache(config.database_path, subscriber, item_id, rating, "queued", "digest")
            stats["cached"] += 1
    return stats


def rate_news_items(
    config: NewsServerConfig,
    items: list[tuple[int, dict[str, object]]],
    subscriber: NewsSubscriberConfig,
    preference_features: dict[str, object],
) -> list[dict[str, object]]:
    """Ask AstrBot to classify and rate a batch of news events."""

    if not config.astrbot.api_key:
        return [
            fallback_rating(item_id, item, "missing astrbot api_key")
            for item_id, item in items
        ]
    prompt = build_rating_prompt(items, subscriber, preference_features)
    response_text = astrbot_chat(config.astrbot, prompt, subscriber)
    parsed = parse_json_object(response_text)
    raw_items = []
    if isinstance(parsed, dict):
        raw = parsed.get("items") or parsed.get("ratings") or parsed.get("data")
        raw_items = raw if isinstance(raw, list) else []
    ratings = [item for item in raw_items if isinstance(item, dict)]
    if not ratings:
        return [fallback_rating(item_id, item, response_text) for item_id, item in items]
    normalized = []
    for item_id, item in items:
        rating = find_rating_for_item(ratings, item_id)
        normalized.append(normalize_rating(rating, item_id, item, raw_response=response_text))
    return normalized


def subscriber_preference_features(
    config: NewsServerConfig,
    subscriber: NewsSubscriberConfig,
) -> dict[str, object]:
    """Return structured user preference features, generating them when needed."""

    preference_text = subscriber.news_preference.strip()
    if not preference_text:
        return {}
    cached = load_preference_features(config.database_path, subscriber.name, preference_text)
    if cached is not None:
        return cached
    if not config.astrbot.api_key:
        features = {"preference_text": preference_text}
        save_preference_features(config.database_path, subscriber.name, preference_text, features)
        return features
    prompt = build_preference_prompt(preference_text)
    response_text = astrbot_chat(config.astrbot, prompt, subscriber)
    parsed = parse_json_object(response_text)
    features = parsed if isinstance(parsed, dict) else {"preference_text": preference_text}
    save_preference_features(config.database_path, subscriber.name, preference_text, features)
    return features


def build_preference_prompt(preference_text: str) -> str:
    """Build a prompt that turns natural-language user preferences into features."""

    return (
        "你是新闻偏好解析器。将用户自然语言偏好提取为结构化特征。"
        "只返回 JSON, 不要 Markdown。字段包括: focus_categories(array), "
        "focus_markets(array), focus_assets(array), boost_rules(array), "
        "downrank_rules(array), discard_rules(array), language(string)。\n\n"
        f"用户偏好:\n{preference_text}"
    )


def build_rating_prompt(
    items: list[tuple[int, dict[str, object]]],
    subscriber: NewsSubscriberConfig,
    preference_features: dict[str, object],
) -> str:
    """Build the batch rating prompt."""

    parts = [
        format_news_part_with_id(item_id, index + 1, item)
        for index, (item_id, item) in enumerate(items)
    ]
    preference_text = subscriber.news_preference.strip()
    features_text = json.dumps(preference_features, ensure_ascii=False, sort_keys=True)
    return (
        "你是新闻事件分拣器。只做事件提取、分类、重要程度和紧急程度评级; "
        "不要写投资建议, 不要评论分析。\n"
        "根据用户偏好调整评级: 符合偏好的事件可提高重要程度或紧急程度; "
        "用户明确不关心或缺少明确事件事实的信息应丢弃。\n"
        "分类必须从以下类别中选择: 宏观经济, 政策监管, 地缘政治, 军事冲突, "
        "A股市场, 行业产业, 公司事件, 商品能源, 外汇利率, 海外市场, 其他。\n"
        "importance 和 urgency 都是 1-5 的整数。"
        "重要但不紧急的新闻 urgency 应较低; 紧急表示需要实时知道事件本身。\n"
        "只返回 JSON, 不要 Markdown。格式: "
        '{"items":[{"news_id":123,"keep":true,"category":"政策监管",'
        '"importance":5,"urgency":4,"event":"一句话事件事实"}]}。\n\n'
        f"用户自然语言偏好:\n{preference_text or '无'}\n\n"
        f"用户偏好特征:\n{features_text}\n\n"
        f"新闻列表:\n{'\n\n'.join(parts)}"
    )


def format_news_part_with_id(item_id: int, index: int, item: dict[str, object]) -> str:
    """Format one news item with its database id."""

    return f"news_id: {item_id}\n{format_news_part(index, item)}"


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


def route_rating(subscriber: NewsSubscriberConfig, rating: dict[str, object]) -> str:
    """Return discard, realtime, or digest for one rating."""

    importance = int(rating.get("importance") or 0)
    urgency = int(rating.get("urgency") or 0)
    if not rating.get("keep") or importance < subscriber.min_keep_importance:
        return "discard"
    if (
        importance >= subscriber.realtime_min_importance
        and urgency >= subscriber.realtime_min_urgency
    ):
        return "realtime"
    return "digest"


def rating_to_review(rating: dict[str, object]) -> dict[str, object]:
    """Convert a rating into the existing review storage shape."""

    return {
        "push": bool(rating.get("keep")),
        "importance": int(rating.get("importance") or 0),
        "urgent": int(rating.get("urgency") or 0) >= 4,
        "markets": [str(rating.get("category") or "其他")],
        "assets": [],
        "message": str(rating.get("event") or ""),
        "raw_response": str(rating.get("raw_response") or ""),
    }


def format_realtime_message(item: dict[str, object], rating: dict[str, object]) -> str:
    """Create a direct realtime event push message."""

    lines = [
        f"【紧急新闻】{rating.get('category') or '其他'}",
        "",
        str(rating.get("event") or item.get("title") or "").strip(),
        "",
        f"时间: {item.get('published_at') or '未知'}",
        f"来源: {item.get('provider') or item.get('source') or '未知'}",
    ]
    url = str(item.get("url") or "").strip()
    if url:
        lines.append(f"链接: {url}")
    return "\n".join(line for line in lines if line is not None)


def deliver_message(
    config: NewsServerConfig,
    subscriber: NewsSubscriberConfig,
    item_id: int,
    message: str,
) -> dict[str, int]:
    """Deliver a prepared message now or through the quiet-hours queue."""

    if not message.strip():
        return {"skipped": 1, "queued": 0, "sent": 0}
    if is_quiet_time(config, subscriber):
        enqueue_delivery(config.database_path, subscriber.name, subscriber.umo, item_id, message)
        return {"skipped": 0, "queued": 1, "sent": 0}
    try:
        astrbot_send_message(config.astrbot, subscriber.umo, message)
        record_delivery(
            config.database_path,
            subscriber.name,
            subscriber.umo,
            item_id,
            message,
            "sent",
            "",
        )
        return {"skipped": 0, "queued": 0, "sent": 1}
    except Exception as exc:
        record_delivery(
            config.database_path,
            subscriber.name,
            subscriber.umo,
            item_id,
            message,
            "failed",
            f"{type(exc).__name__}: {exc}",
        )
        return {"skipped": 1, "queued": 0, "sent": 0}


def flush_digest_cache(config: NewsServerConfig) -> dict[str, int]:
    """Summarize and push digest-cache items when count or schedule is due."""

    stats = {"queued": 0, "sent": 0, "skipped": 0}
    for subscriber in config.subscribers:
        if not subscriber.enabled:
            continue
        rows = digest_cache_rows(
            config.database_path,
            subscriber,
            limit=subscriber.digest_max_items,
        )
        if not rows or not digest_due(config, subscriber, len(rows)):
            continue
        message = build_digest_message(config, subscriber, rows)
        first_item_id = int(rows[0]["news_item_id"]) if rows else 0
        delivery = deliver_message(config, subscriber, first_item_id, message)
        for key in ("queued", "sent", "skipped"):
            stats[key] += int(delivery.get(key, 0))
        if int(delivery.get("queued", 0)) or int(delivery.get("sent", 0)):
            mark_news_cache_sent(config.database_path, [int(row["id"]) for row in rows])
    return stats


def digest_due(
    config: NewsServerConfig,
    subscriber: NewsSubscriberConfig,
    queued_count: int,
) -> bool:
    """Return whether a subscriber's digest cache should be flushed."""

    if queued_count >= max(subscriber.digest_min_items, 1):
        return True
    digest_times = subscriber.digest_times or ("10:00", "12:00", "15:10", "20:30")
    now_text = datetime.now(ZoneInfo(config.timezone)).strftime("%H:%M")
    return now_text in set(digest_times)


def build_digest_message(
    config: NewsServerConfig,
    subscriber: NewsSubscriberConfig,
    rows: list[sqlite3.Row],
) -> str:
    """Ask the agent to summarize cached news into final push text."""

    if not config.astrbot.api_key:
        return fallback_digest_message(rows)
    item_texts = [format_digest_cache_row(index + 1, row) for index, row in enumerate(rows)]
    prompt = build_digest_prompt(subscriber, item_texts)
    if len(prompt) <= subscriber.max_context_chars:
        return astrbot_chat(config.astrbot, prompt, subscriber).strip()
    batches = split_text_batches(item_texts, subscriber.max_context_chars)
    summaries = [
        astrbot_chat(
            config.astrbot,
            build_digest_batch_prompt(subscriber, batch, index, len(batches)),
            subscriber,
        )
        for index, batch in enumerate(batches, start=1)
    ]
    return astrbot_chat(
        config.astrbot,
        build_digest_final_prompt(subscriber, summaries),
        subscriber,
    ).strip()


def build_digest_prompt(subscriber: NewsSubscriberConfig, item_texts: list[str]) -> str:
    """Build the final digest formatting prompt."""

    return (
        "你是新闻汇总排版器。只整理事件事实, 不做投资建议, 不做评论分析。"
        "请合并重复事件, 按类别归纳, 类别内按重要程度和紧急程度排序。"
        "输出可直接发送给用户的中文纯文本, 不要 JSON, 不要 Markdown 表格, 不要代码块。\n\n"
        f"用户偏好:\n{subscriber.news_preference or subscriber.prompt_prefix or '无'}\n\n"
        f"额外输出要求:\n{subscriber.prompt_suffix or '无'}\n\n"
        f"新闻缓存:\n{'\n\n'.join(item_texts)}"
    )


def build_digest_batch_prompt(
    subscriber: NewsSubscriberConfig,
    item_texts: list[str],
    batch_index: int,
    batch_count: int,
) -> str:
    """Build one digest compression prompt."""

    return (
        f"这是新闻缓存批次 {batch_index}/{batch_count}。"
        "只提取事件事实, 按类别压缩为简洁要点, 不做分析评论。\n\n"
        f"用户偏好:\n{subscriber.news_preference or subscriber.prompt_prefix or '无'}\n\n"
        f"{'\n\n'.join(item_texts)}"
    )


def build_digest_final_prompt(subscriber: NewsSubscriberConfig, summaries: list[str]) -> str:
    """Build the final digest prompt from compressed batch summaries."""

    summary_text = "\n\n".join(
        f"批次 {index}:\n{summary}" for index, summary in enumerate(summaries, start=1)
    )
    return (
        "请将以下批次摘要合并为最终新闻汇总推送。只保留事件事实, 不做投资建议或评论分析。"
        "按类别组织, 合并重复, 按重要程度排序, 输出中文纯文本。\n\n"
        f"用户偏好:\n{subscriber.news_preference or subscriber.prompt_prefix or '无'}\n\n"
        f"额外输出要求:\n{subscriber.prompt_suffix or '无'}\n\n"
        f"{summary_text}"
    )


def format_digest_cache_row(index: int, row: sqlite3.Row) -> str:
    """Format one cached item for the digest agent."""

    return (
        f"[{index}] news_id: {row['news_item_id']}\n"
        f"类别: {row['category']}\n"
        f"重要程度: {row['importance']}\n"
        f"紧急程度: {row['urgency']}\n"
        f"事件: {row['event']}\n"
        f"标题: {row['title']}\n"
        f"摘要: {row['summary']}\n"
        f"来源: {row['provider']} / {row['source']}\n"
        f"时间: {row['published_at']}\n"
        f"链接: {row['url']}"
    )


def fallback_digest_message(rows: list[sqlite3.Row]) -> str:
    """Build a simple digest when no agent is configured."""

    lines = ["【新闻汇总】", ""]
    for row in rows:
        lines.append(f"- [{row['category']}] {row['event'] or row['title']}")
    return "\n".join(lines)


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


def review_news_item(
    config: NewsServerConfig,
    item: dict[str, object],
    subscriber: NewsSubscriberConfig | None = None,
) -> dict[str, object]:
    """Ask AstrBot whether a news item should be pushed."""

    if not config.astrbot.api_key:
        return {
            "push": False,
            "importance": 0,
            "urgent": False,
            "markets": [],
            "assets": [],
            "message": "",
            "raw_response": "missing astrbot api_key",
        }
    prompt = build_review_prompt(item, subscriber)
    response_text = astrbot_chat(config.astrbot, prompt, subscriber)
    parsed = parse_json_object(response_text)
    if parsed is None:
        return {
            "push": False,
            "importance": 0,
            "urgent": False,
            "markets": [],
            "assets": [],
            "message": "",
            "raw_response": response_text,
        }
    return {
        "push": bool(parsed.get("push")),
        "importance": int(parsed.get("importance") or 0),
        "urgent": bool(parsed.get("urgent")),
        "markets": list_value(parsed.get("markets")),
        "assets": list_value(parsed.get("assets")),
        "message": str(parsed.get("message") or parsed.get("summary") or ""),
        "raw_response": response_text,
    }


def review_news_items(
    config: NewsServerConfig,
    items: list[tuple[int, dict[str, object]]],
    subscriber: NewsSubscriberConfig,
) -> dict[str, object]:
    """Review a subscriber-specific batch, splitting when it exceeds char budget."""

    if not items:
        return empty_review("empty news batch")
    if len(items) == 1:
        return review_news_item(config, items[0][1], subscriber)
    item_texts = [format_news_part(index + 1, item) for index, (_item_id, item) in enumerate(items)]
    prompt = build_multi_item_prompt(subscriber, item_texts)
    if len(prompt) <= subscriber.max_context_chars:
        return parse_review_response(astrbot_chat(config.astrbot, prompt, subscriber))

    batches = split_text_batches(item_texts, subscriber.max_context_chars)
    summaries: list[str] = []
    for index, batch in enumerate(batches, start=1):
        batch_prompt = build_batch_summary_prompt(subscriber, batch, index, len(batches))
        summaries.append(astrbot_chat(config.astrbot, batch_prompt, subscriber))
    final_prompt = build_final_summary_prompt(subscriber, summaries)
    return parse_review_response(astrbot_chat(config.astrbot, final_prompt, subscriber))


def parse_review_response(response_text: str) -> dict[str, object]:
    """Parse one AstrBot review JSON response."""

    parsed = parse_json_object(response_text)
    if parsed is None:
        return empty_review(response_text)
    return {
        "push": bool(parsed.get("push")),
        "importance": int(parsed.get("importance") or 0),
        "urgent": bool(parsed.get("urgent")),
        "markets": list_value(parsed.get("markets")),
        "assets": list_value(parsed.get("assets")),
        "message": str(parsed.get("message") or parsed.get("summary") or ""),
        "raw_response": response_text,
    }


def empty_review(raw_response: str) -> dict[str, object]:
    """Return a non-push review."""

    return {
        "push": False,
        "importance": 0,
        "urgent": False,
        "markets": [],
        "assets": [],
        "message": "",
        "raw_response": raw_response,
    }


def build_review_prompt(
    item: dict[str, object],
    subscriber: NewsSubscriberConfig | None = None,
) -> str:
    """Build the AstrBot review prompt."""

    prefix, suffix = prompt_parts(subscriber)
    return f"{prefix}\n\n{format_news_part(1, item)}\n\n{suffix}"


def build_multi_item_prompt(subscriber: NewsSubscriberConfig, item_texts: list[str]) -> str:
    """Build one prompt for a group of news items."""

    prefix, suffix = prompt_parts(subscriber)
    return f"{prefix}\n\n新闻列表:\n{'\n\n'.join(item_texts)}\n\n{suffix}"


def build_batch_summary_prompt(
    subscriber: NewsSubscriberConfig,
    item_texts: list[str],
    batch_index: int,
    batch_count: int,
) -> str:
    """Build a map-step prompt for one batch."""

    prefix, _suffix = prompt_parts(subscriber)
    return (
        f"{prefix}\n\n"
        f"这是新闻批次 {batch_index}/{batch_count}。请只提取本批次中可能值得投资关注的事实增量, "
        "输出简洁中文要点, 暂时不要做最终推送决定。\n\n"
        f"{'\n\n'.join(item_texts)}"
    )


def build_final_summary_prompt(subscriber: NewsSubscriberConfig, summaries: list[str]) -> str:
    """Build the reduce-step final prompt."""

    prefix, suffix = prompt_parts(subscriber)
    summary_text = "\n\n".join(
        f"批次 {index} 摘要:\n{summary}" for index, summary in enumerate(summaries, start=1)
    )
    return f"{prefix}\n\n以下是各批次压缩摘要, 请据此做最终推送判断:\n{summary_text}\n\n{suffix}"


def prompt_parts(subscriber: NewsSubscriberConfig | None) -> tuple[str, str]:
    """Return prompt prefix and suffix for review requests."""

    user_prefix = subscriber.prompt_prefix.strip() if subscriber else ""
    user_suffix = subscriber.prompt_suffix.strip() if subscriber else ""
    prefix = (
        "你是投资新闻推送审核 agent。判断新闻是否值得向用户推送。"
        "重点关注政治、军事、政策、经济和市场影响。"
    )
    if user_prefix:
        prefix = f"{prefix}\n\n用户筛选偏好:\n{user_prefix}"
    suffix = (
        "只返回 JSON, 不要 Markdown。字段: push(boolean), importance(1-5), "
        "urgent(boolean), markets(array), assets(array), message(string)。"
        "message 是会被直接发送给用户的最终推送正文, 必须完成排版优化。"
        "要求: 使用简洁中文; 合并重复信息; 包含影响市场/资产和不确定性; "
        "用清晰标题或首行摘要开头; 多要点用短行分隔; "
        "避免冗长段落、JSON、Markdown 表格、代码块和解释性废话。"
    )
    if user_suffix:
        suffix = f"{suffix}\n\n额外输出要求:\n{user_suffix}"
    return prefix, suffix


def format_news_part(index: int, item: dict[str, object]) -> str:
    """Format one news item for review prompts."""

    return (
        f"[{index}]\n"
        f"标题: {item.get('title')}\n"
        f"摘要: {item.get('summary')}\n"
        f"配置源: {item.get('source')}\n"
        f"来源: {item.get('provider')}\n"
        f"时间: {item.get('published_at')}\n"
        f"链接: {item.get('url')}\n"
    )


def split_text_batches(items: list[str], max_chars: int) -> list[list[str]]:
    """Split formatted news items into character-limited batches."""

    budget = max(max_chars, 1000)
    batches: list[list[str]] = []
    current: list[str] = []
    current_size = 0
    for item in items:
        item_size = len(item) + 2
        if current and current_size + item_size > budget:
            batches.append(current)
            current = []
            current_size = 0
        current.append(item)
        current_size += item_size
    if current:
        batches.append(current)
    return batches


def astrbot_chat(
    config: AstrBotConfig,
    message: str,
    subscriber: NewsSubscriberConfig | None = None,
) -> str:
    """Send a review prompt to AstrBot chat API and return response text."""

    payload = {
        "username": subscriber.review_username if subscriber else config.review_username,
        "session_id": subscriber.review_session_id if subscriber else config.review_session_id,
        "message": message,
        "enable_streaming": False,
    }
    data = request_astrbot(config, "/api/v1/chat", payload)
    return extract_text_response(data)


def astrbot_send_message(config: AstrBotConfig, umo: str, message: str) -> JsonValue:
    """Send a proactive message through AstrBot IM API."""

    return request_astrbot(config, "/api/v1/im/message", {"umo": umo, "message": message})


def request_astrbot(config: AstrBotConfig, path: str, payload: dict[str, object]) -> JsonValue:
    """POST JSON to AstrBot and parse JSON or SSE JSON responses."""

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        f"{config.base_url.rstrip('/')}{path}",
        data=body,
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "AMStock/0.1",
        },
        method="POST",
    )
    with urlopen(request, timeout=config.timeout) as response:
        raw = response.read().decode("utf-8-sig")
    try:
        return cast("JsonValue", json.loads(raw))
    except json.JSONDecodeError:
        return parse_sse_payload(raw)


def deliver_review(
    config: NewsServerConfig,
    item_id: int,
    review: dict[str, object],
    subscriber: NewsSubscriberConfig,
) -> dict[str, int]:
    """Deliver one subscriber-specific reviewed item."""

    if not review.get("push"):
        return {"skipped": 1, "queued": 0, "sent": 0}
    if int(review.get("importance") or 0) < subscriber.min_importance:
        return {"skipped": 1, "queued": 0, "sent": 0}
    if subscriber.markets and not set(subscriber.markets).intersection(
        str(item) for item in list_value(review.get("markets"))
    ):
        return {"skipped": 1, "queued": 0, "sent": 0}
    message = str(review.get("message") or "")
    if not message:
        return {"skipped": 1, "queued": 0, "sent": 0}
    if is_quiet_time(config, subscriber) and not review.get("urgent"):
        enqueue_delivery(
            config.database_path,
            subscriber.name,
            subscriber.umo,
            item_id,
            message,
        )
        return {"skipped": 0, "queued": 1, "sent": 0}
    try:
        astrbot_send_message(config.astrbot, subscriber.umo, message)
        record_delivery(
            config.database_path,
            subscriber.name,
            subscriber.umo,
            item_id,
            message,
            "sent",
            "",
        )
        return {"skipped": 0, "queued": 0, "sent": 1}
    except Exception as exc:
        record_delivery(
            config.database_path,
            subscriber.name,
            subscriber.umo,
            item_id,
            message,
            "failed",
            f"{type(exc).__name__}: {exc}",
        )
        return {"skipped": 1, "queued": 0, "sent": 0}


def flush_news_queue(
    config: NewsServerConfig | None = None,
    *,
    respect_flush_policy: bool = False,
) -> dict[str, object]:
    """Send queued messages when quiet hours are over."""

    cfg = config or load_news_server_config()
    ensure_news_schema(cfg.database_path)
    rows = queued_deliveries(cfg.database_path)
    sent = 0
    failed = 0
    remaining_quiet = 0
    waiting_manual_flush = 0
    for row in rows:
        subscriber = find_subscriber(cfg, str(row["subscriber_name"]), str(row["umo"]))
        if subscriber and is_quiet_time(cfg, subscriber):
            remaining_quiet += 1
            continue
        if respect_flush_policy and subscriber and not subscriber.quiet_hours.flush_on_end:
            waiting_manual_flush += 1
            continue
        try:
            astrbot_send_message(cfg.astrbot, str(row["umo"]), str(row["message"]))
            mark_delivery(cfg.database_path, int(row["id"]), "sent", "")
            sent += 1
        except Exception as exc:
            mark_delivery(
                cfg.database_path,
                int(row["id"]),
                "failed",
                f"{type(exc).__name__}: {exc}",
            )
            failed += 1
    return {
        "ok": True,
        "function": "news-flush",
        "sent": sent,
        "failed": failed,
        "remaining_quiet": remaining_quiet,
        "waiting_manual_flush": waiting_manual_flush,
    }


def news_queue_payload(
    config: NewsServerConfig | None = None,
    *,
    limit: int = 50,
) -> dict[str, object]:
    """Return queued delivery records."""

    cfg = config or load_news_server_config()
    ensure_news_schema(cfg.database_path)
    rows = queued_deliveries(cfg.database_path, limit=limit)
    return {
        "ok": True,
        "function": "news-queue",
        "rows": len(rows),
        "returned_rows": len(rows),
        "data": [dict(row) for row in rows],
    }


def news_list_payload(
    config: NewsServerConfig | None = None,
    *,
    limit: int = 50,
    source: str = "",
    provider: str = "",
    query: str = "",
    since: str = "",
    subscriber_name: str = "",
    delivery_status: str = "",
    review_push: str | bool | None = None,
) -> dict[str, object]:
    """Return stored news items matching read-only filters."""

    cfg = config or load_news_server_config()
    ensure_news_schema(cfg.database_path)
    parsed_review_push = optional_bool(review_push)
    rows = list_news_items(
        cfg.database_path,
        limit=limit,
        source=source,
        provider=provider,
        query=query,
        since=since,
        subscriber_name=subscriber_name,
        delivery_status=delivery_status,
        review_push=parsed_review_push,
    )
    data = [news_list_row_payload(row) for row in rows]
    return {
        "ok": True,
        "function": "news-list",
        "rows": len(data),
        "returned_rows": len(data),
        "data": data,
    }


def replay_news(
    config: NewsServerConfig | None = None,
    *,
    limit: int = 50,
    since: str = "",
    subscriber_name: str = "",
    include_sent: bool = False,
) -> dict[str, object]:
    """Replay stored news through subscriber review and delivery."""

    cfg = config or load_news_server_config()
    ensure_news_schema(cfg.database_path)
    rows = replay_news_items(
        cfg.database_path,
        limit=limit,
        since=since,
        subscriber_name=subscriber_name,
        include_sent=include_sent,
    )
    stats = {
        "items": len(rows),
        "reviewed": 0,
        "queued": 0,
        "sent": 0,
        "skipped": 0,
    }
    items = [row_to_news_item(row) for row in rows]
    for subscriber in cfg.subscribers:
        if not subscriber.enabled:
            continue
        if subscriber_name and subscriber.name != subscriber_name:
            continue
        accepted = [
            (int(row["id"]), item)
            for row, item in zip(rows, items, strict=True)
            if subscriber_accepts_source(subscriber, item)
            and (
                include_sent
                or not delivery_sent_exists(cfg.database_path, subscriber, int(row["id"]))
            )
        ]
        if not accepted:
            continue
        review = review_news_items(cfg, accepted, subscriber)
        stats["reviewed"] = int(stats["reviewed"]) + len(accepted)
        for item_id, _item in accepted:
            save_news_review(cfg.database_path, item_id, review, subscriber)
        delivery = deliver_review(cfg, accepted[0][0], review, subscriber)
        for key in ("queued", "sent", "skipped"):
            stats[key] = int(stats[key]) + int(delivery.get(key, 0))
    return {"ok": True, "function": "news-replay", **stats}


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
    subscriber: NewsSubscriberConfig | None = None,
) -> None:
    """Persist an AstrBot review result."""

    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            INSERT INTO news_reviews
            (
                news_item_id, subscriber_name, review_username, review_session_id,
                push, importance, urgent, markets,
                assets, message, raw_response, reviewed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id,
                subscriber.name if subscriber else "",
                subscriber.review_username if subscriber else "",
                subscriber.review_session_id if subscriber else "",
                1 if review.get("push") else 0,
                int(review.get("importance") or 0),
                1 if review.get("urgent") else 0,
                json.dumps(list_value(review.get("markets")), ensure_ascii=False),
                json.dumps(list_value(review.get("assets")), ensure_ascii=False),
                str(review.get("message") or ""),
                str(review.get("raw_response") or ""),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )


def enqueue_delivery(
    path: Path,
    subscriber_name: str,
    umo: str,
    item_id: int,
    message: str,
) -> None:
    """Queue a message for later delivery."""

    record_delivery(path, subscriber_name, umo, item_id, message, "queued", "")


def record_delivery(
    path: Path,
    subscriber_name: str,
    umo: str,
    item_id: int,
    message: str,
    status: str,
    error: str,
) -> None:
    """Record one delivery attempt."""

    now = datetime.now().isoformat(timespec="seconds")
    sent_at = now if status == "sent" else ""
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            INSERT INTO news_delivery_queue
            (subscriber_name, umo, news_item_id, message, status, error, created_at, sent_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (subscriber_name, umo, item_id, message, status, error, now, sent_at),
        )


def queued_deliveries(path: Path, *, limit: int = 100) -> list[sqlite3.Row]:
    """Return queued deliveries."""

    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT
                id, subscriber_name, umo, news_item_id,
                message, status, error, created_at, sent_at
            FROM news_delivery_queue
            WHERE status = 'queued'
            ORDER BY id
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return list(rows)


def mark_delivery(path: Path, delivery_id: int, status: str, error: str) -> None:
    """Mark a queued delivery as sent or failed."""

    sent_at = datetime.now().isoformat(timespec="seconds") if status == "sent" else ""
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE news_delivery_queue SET status = ?, error = ?, sent_at = ? WHERE id = ?",
            (status, error, sent_at, delivery_id),
        )


def load_preference_features(
    path: Path,
    subscriber_name: str,
    preference_text: str,
) -> dict[str, object] | None:
    """Load cached structured preference features when the source text matches."""

    with sqlite3.connect(path) as conn:
        row = conn.execute(
            """
            SELECT preference_features_json
            FROM news_subscriber_preferences
            WHERE subscriber_name = ? AND preference_text = ?
            """,
            (subscriber_name, preference_text),
        ).fetchone()
    if row is None:
        return None
    try:
        parsed = json.loads(str(row[0]))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def save_preference_features(
    path: Path,
    subscriber_name: str,
    preference_text: str,
    features: dict[str, object],
) -> None:
    """Persist structured preference features."""

    now = datetime.now().isoformat(timespec="seconds")
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            INSERT INTO news_subscriber_preferences
                (subscriber_name, preference_text, preference_features_json, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(subscriber_name) DO UPDATE SET
                preference_text = excluded.preference_text,
                preference_features_json = excluded.preference_features_json,
                updated_at = excluded.updated_at
            """,
            (subscriber_name, preference_text, json.dumps(features, ensure_ascii=False), now),
        )


def upsert_news_cache(
    path: Path,
    subscriber: NewsSubscriberConfig,
    item_id: int,
    rating: dict[str, object],
    status: str,
    delivery_mode: str,
) -> None:
    """Insert or update a subscriber-specific news cache decision."""

    now = datetime.now().isoformat(timespec="seconds")
    sent_at = now if status == "sent" else ""
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            INSERT INTO news_cache
            (
                subscriber_name, news_item_id, category, importance, urgency, event,
                status, delivery_mode, rating_raw_json, queued_at, sent_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(subscriber_name, news_item_id) DO UPDATE SET
                category = excluded.category,
                importance = excluded.importance,
                urgency = excluded.urgency,
                event = excluded.event,
                status = excluded.status,
                delivery_mode = excluded.delivery_mode,
                rating_raw_json = excluded.rating_raw_json,
                sent_at = excluded.sent_at
            """,
            (
                subscriber.name,
                item_id,
                str(rating.get("category") or "其他"),
                int(rating.get("importance") or 0),
                int(rating.get("urgency") or 0),
                str(rating.get("event") or ""),
                status,
                delivery_mode,
                str(rating.get("raw_response") or ""),
                now,
                sent_at,
            ),
        )


def digest_cache_rows(
    path: Path,
    subscriber: NewsSubscriberConfig,
    *,
    limit: int,
) -> list[sqlite3.Row]:
    """Return queued digest-cache rows for a subscriber."""

    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT
                c.id, c.subscriber_name, c.news_item_id, c.category, c.importance,
                c.urgency, c.event, c.status, c.delivery_mode, c.queued_at,
                n.source, n.provider, n.title, n.summary, n.url, n.published_at
            FROM news_cache c
            JOIN news_items n ON n.id = c.news_item_id
            WHERE c.subscriber_name = ?
              AND c.status = 'queued'
              AND c.delivery_mode = 'digest'
            ORDER BY c.importance DESC, c.urgency DESC, c.id
            LIMIT ?
            """,
            (subscriber.name, max(limit, 1)),
        ).fetchall()
    return list(rows)


def mark_news_cache_sent(path: Path, cache_ids: list[int]) -> None:
    """Mark digest-cache rows as processed into a delivery."""

    if not cache_ids:
        return
    now = datetime.now().isoformat(timespec="seconds")
    placeholders = ", ".join("?" for _ in cache_ids)
    with sqlite3.connect(path) as conn:
        conn.execute(
            f"UPDATE news_cache SET status = 'sent', sent_at = ? WHERE id IN ({placeholders})",
            (now, *cache_ids),
        )


def list_news_items(
    path: Path,
    *,
    limit: int,
    source: str,
    provider: str,
    query: str,
    since: str,
    subscriber_name: str,
    delivery_status: str,
    review_push: bool | None,
) -> list[sqlite3.Row]:
    """Query stored news items with optional review/delivery filters."""

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
        clauses.append("(n.title LIKE ? OR n.summary LIKE ? OR n.raw_json LIKE ?)")
        params.extend((like, like, like))
    if since:
        clauses.append("(n.first_seen_at >= ? OR n.published_at >= ?)")
        params.extend((since, since))
    if review_push is not None:
        clauses.append(
            """
            EXISTS (
                SELECT 1 FROM news_reviews rf
                WHERE rf.news_item_id = n.id
                  AND rf.push = ?
                  AND (? = '' OR rf.subscriber_name = ?)
            )
            """
        )
        params.extend((1 if review_push else 0, subscriber_name, subscriber_name))
    if delivery_status:
        clauses.append(
            """
            EXISTS (
                SELECT 1 FROM news_delivery_queue df
                WHERE df.news_item_id = n.id
                  AND df.status = ?
                  AND (? = '' OR df.subscriber_name = ?)
            )
            """
        )
        params.extend((delivery_status, subscriber_name, subscriber_name))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(max(limit, 1))
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT
                n.id, n.source, n.provider, n.title, n.summary, n.url,
                n.published_at, n.fingerprint, n.first_seen_at,
                (
                    SELECT r.subscriber_name FROM news_reviews r
                    WHERE r.news_item_id = n.id
                      AND (? = '' OR r.subscriber_name = ?)
                    ORDER BY r.id DESC LIMIT 1
                ) AS review_subscriber_name,
                (
                    SELECT r.push FROM news_reviews r
                    WHERE r.news_item_id = n.id
                      AND (? = '' OR r.subscriber_name = ?)
                    ORDER BY r.id DESC LIMIT 1
                ) AS review_push,
                (
                    SELECT r.importance FROM news_reviews r
                    WHERE r.news_item_id = n.id
                      AND (? = '' OR r.subscriber_name = ?)
                    ORDER BY r.id DESC LIMIT 1
                ) AS review_importance,
                (
                    SELECT r.urgent FROM news_reviews r
                    WHERE r.news_item_id = n.id
                      AND (? = '' OR r.subscriber_name = ?)
                    ORDER BY r.id DESC LIMIT 1
                ) AS review_urgent,
                (
                    SELECT r.message FROM news_reviews r
                    WHERE r.news_item_id = n.id
                      AND (? = '' OR r.subscriber_name = ?)
                    ORDER BY r.id DESC LIMIT 1
                ) AS review_message,
                (
                    SELECT d.status FROM news_delivery_queue d
                    WHERE d.news_item_id = n.id
                      AND (? = '' OR d.subscriber_name = ?)
                    ORDER BY d.id DESC LIMIT 1
                ) AS delivery_status
            FROM news_items n
            {where}
            ORDER BY n.id DESC
            LIMIT ?
            """,
            (
                subscriber_name,
                subscriber_name,
                subscriber_name,
                subscriber_name,
                subscriber_name,
                subscriber_name,
                subscriber_name,
                subscriber_name,
                subscriber_name,
                subscriber_name,
                subscriber_name,
                subscriber_name,
                *params,
            ),
        ).fetchall()
    return list(rows)


def news_list_row_payload(row: sqlite3.Row) -> dict[str, object]:
    """Convert a news list query row to JSON payload."""

    latest_review = None
    if row["review_subscriber_name"] is not None:
        latest_review = {
            "subscriber_name": row["review_subscriber_name"],
            "push": bool(row["review_push"]),
            "importance": int(row["review_importance"] or 0),
            "urgent": bool(row["review_urgent"]),
            "message": str(row["review_message"] or ""),
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
        "latest_review": latest_review,
        "delivery_status": row["delivery_status"],
    }


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


def replay_news_items(
    path: Path,
    *,
    limit: int,
    since: str,
    subscriber_name: str,
    include_sent: bool,
) -> list[sqlite3.Row]:
    """Return stored news items eligible for replay."""

    clauses: list[str] = []
    params: list[object] = []
    if since:
        clauses.append("(first_seen_at >= ? OR published_at >= ?)")
        params.extend((since, since))
    if not include_sent and subscriber_name:
        clauses.append(
            """
            NOT EXISTS (
                SELECT 1 FROM news_delivery_queue d
                WHERE d.news_item_id = news_items.id
                  AND d.subscriber_name = ?
                  AND d.status = 'sent'
            )
            """
        )
        params.append(subscriber_name)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(max(limit, 1))
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT
                id, source, provider, title, summary, url,
                published_at, fingerprint, raw_json, first_seen_at
            FROM news_items
            {where}
            ORDER BY id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return list(reversed(rows))


def row_to_news_item(row: sqlite3.Row) -> dict[str, object]:
    """Convert a news_items row to the review item shape."""

    return {
        "source": str(row["source"]),
        "provider": str(row["provider"]),
        "title": str(row["title"]),
        "summary": str(row["summary"]),
        "url": str(row["url"]),
        "published_at": str(row["published_at"]),
        "fingerprint": str(row["fingerprint"]),
        "raw_json": str(row["raw_json"]),
    }


def delivery_sent_exists(
    path: Path,
    subscriber: NewsSubscriberConfig,
    item_id: int,
) -> bool:
    """Return whether a subscriber already has a sent delivery for an item."""

    with sqlite3.connect(path) as conn:
        row = conn.execute(
            """
            SELECT 1 FROM news_delivery_queue
            WHERE news_item_id = ?
              AND subscriber_name = ?
              AND status = 'sent'
            LIMIT 1
            """,
            (item_id, subscriber.name),
        ).fetchone()
    return row is not None


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


def subscriber_accepts_source(
    subscriber: NewsSubscriberConfig,
    item: dict[str, object],
) -> bool:
    """Return whether a subscriber accepts the item's source/provider."""

    if not subscriber.sources:
        return True
    accepted = {source.lower() for source in subscriber.sources}
    item_sources = {
        str(item.get("source") or "").lower(),
        str(item.get("provider") or "").lower(),
    }
    return bool(accepted.intersection(item_sources))


def find_subscriber(
    config: NewsServerConfig,
    name: str,
    umo: str,
) -> NewsSubscriberConfig | None:
    """Find the configured subscriber for a queued delivery."""

    for subscriber in config.subscribers:
        if subscriber.name == name and subscriber.umo == umo:
            return subscriber
    for subscriber in config.subscribers:
        if subscriber.umo == umo:
            return subscriber
    return None


def is_quiet_time(
    config: NewsServerConfig,
    subscriber: NewsSubscriberConfig | datetime | None = None,
    now: datetime | None = None,
) -> bool:
    """Return whether the current time is inside quiet hours."""

    if isinstance(subscriber, datetime):
        now = subscriber
        subscriber = None
    quiet_hours = subscriber.quiet_hours if subscriber else config.quiet_hours
    if not quiet_hours.enabled:
        return False
    tz = ZoneInfo(config.timezone)
    current = now.astimezone(tz) if now else datetime.now(tz)
    start = parse_hhmm(quiet_hours.start)
    end = parse_hhmm(quiet_hours.end)
    current_time = current.time().replace(second=0, microsecond=0)
    if start <= end:
        return start <= current_time < end
    return current_time >= start or current_time < end


def parse_hhmm(value: str) -> datetime_time:
    """Parse HH:MM into a time object."""

    hour, minute = value.split(":", 1)
    return datetime_time(int(hour), int(minute))


def next_window_start(config: NewsServerConfig, now: datetime | None = None) -> datetime:
    """Return the next quiet-hours end time."""

    tz = ZoneInfo(config.timezone)
    current = now.astimezone(tz) if now else datetime.now(tz)
    end = parse_hhmm(config.quiet_hours.end)
    candidate = current.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)
    if candidate <= current:
        candidate += timedelta(days=1)
    return candidate


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
