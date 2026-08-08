"""Collector registry for pluggable news source collection."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.error import HTTPError

from amstock.news_io import DEFAULT_NEWS_TIMEOUT_SECONDS, fetch_gdelt_news, fetch_marketaux_news

if TYPE_CHECKING:
    from amstock.news_server import NewsServerConfig, NewsSourceConfig

# Collector callable: takes (source, config, token_index) -> list of normalized item dicts
Collector = Any  # Callable[[NewsSourceConfig, NewsServerConfig | None, int], list[dict[str, object]]]

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_COLLECTORS: dict[str, Collector] = {}


def register_collector(source_type: str, collector: Collector) -> None:
    """Register a collector function for a source type."""
    _COLLECTORS[source_type] = collector


def get_collector(source_type: str) -> Collector:
    """Look up a registered collector, raising ValueError for unknown types."""
    if source_type not in _COLLECTORS:
        msg = f"unsupported news source type {source_type!r}"
        raise ValueError(msg)
    return _COLLECTORS[source_type]


def registered_types() -> frozenset[str]:
    """Return all registered source types."""
    return frozenset(_COLLECTORS.keys())


def collect_source(
    source: NewsSourceConfig,
    config: NewsServerConfig | None = None,
    token_index: int = 0,
) -> list[dict[str, object]]:
    """Collect normalized items from one source via the registry."""
    collector = get_collector(source.type)
    return collector(source, config, token_index)


# ---------------------------------------------------------------------------
# Shared helpers imported from news_server at runtime
# ---------------------------------------------------------------------------


def _import_helpers():
    """Lazy-import shared helpers to avoid circular import issues."""
    from amstock.news_server import (  # noqa: F811
        _MARKETAUX_NEXT_TOKEN_INDEX,
        api_params,
        int_value,
        marketaux_api_params,
        normalize_items,
        source_last_success_at,
        source_proxy_url,
        source_token,
        source_tokens,
        source_next_token_index as _source_next_token_index,
        string_value,
        utc_datetime_param,
    )

    return (
        _MARKETAUX_NEXT_TOKEN_INDEX,
        api_params,
        int_value,
        marketaux_api_params,
        normalize_items,
        source_last_success_at,
        source_proxy_url,
        source_token,
        source_tokens,
        _source_next_token_index,
        string_value,
        utc_datetime_param,
    )


# ---------------------------------------------------------------------------
# Marketaux internal helpers
# ---------------------------------------------------------------------------


def _marketaux_http_error_text(exc: HTTPError) -> str:
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


def _marketaux_token_exhausted_error(exc: HTTPError, body: str) -> bool:
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


def _marketaux_sections(
    source: NewsSourceConfig,
) -> list[tuple[str, dict[str, object]]]:
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


def _collect_marketaux_section(
    source: NewsSourceConfig,
    config: NewsServerConfig | None,
    section_name: str,
    section_params: dict[str, object],
    tokens: tuple[str, ...],
    token_index: int,
) -> tuple[list[dict[str, object]], int, str]:
    """Collect one Marketaux section, trying the next token on quota errors."""
    (
        _MARKETAUX_NEXT_TOKEN_INDEX,
        _api_params,
        _int_value,
        _marketaux_api_params,
        _normalize_items,
        _source_last_success_at,
        _source_proxy_url,
        _source_token,
        _source_tokens,
        _source_next_token_index,
        _string_value,
        _utc_datetime_param,
    ) = _import_helpers()

    attempts = max(len(tokens), 1)
    last_error = ""
    for attempt in range(attempts):
        effective_token_index = token_index + attempt
        token = tokens[effective_token_index % len(tokens)] if tokens else None
        try:
            payload = fetch_marketaux_news(
                params=_marketaux_api_params(source, config, section_params),
                token_value=token,
                proxy_url=_source_proxy_url(source),
                limit=source.limit,
            )
        except HTTPError as exc:
            error_text = _marketaux_http_error_text(exc)
            last_error = f"{section_name}: HTTPError {exc.code}: {error_text}"
            if _marketaux_token_exhausted_error(exc, error_text):
                continue
            return [], effective_token_index + 1, last_error
        except Exception as exc:
            last_error = f"{section_name}: {type(exc).__name__}: {exc}"
            return [], effective_token_index + 1, last_error
        items = _normalize_items(source.name, "marketaux", payload.get("data"))
        return items, effective_token_index + 1, ""
    return [], token_index + attempts, last_error or f"{section_name}: all Marketaux tokens failed"


# ---------------------------------------------------------------------------
# Collector functions
# ---------------------------------------------------------------------------


def collect_gdelt(
    source: NewsSourceConfig,
    config: NewsServerConfig | None = None,
    token_index: int = 0,
) -> list[dict[str, object]]:
    """Collect GDELT news."""
    (
        _MARKETAUX_NEXT_TOKEN_INDEX,
        api_params,
        _int_value,
        _marketaux_api_params,
        normalize_items,
        _source_last_success_at,
        source_proxy_url,
        source_token,
        source_tokens,
        _source_next_token_index,
        _string_value,
        _utc_datetime_param,
    ) = _import_helpers()
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


def collect_marketaux(
    source: NewsSourceConfig,
    config: NewsServerConfig | None = None,
    token_index: int = 0,
) -> list[dict[str, object]]:
    """Collect Marketaux news across configured topic sections."""
    (
        _MARKETAUX_NEXT_TOKEN_INDEX,
        _api_params,
        _int_value,
        _marketaux_api_params,
        _normalize_items,
        _source_last_success_at,
        _source_proxy_url,
        _source_token,
        _source_tokens,
        _source_next_token_index,
        _string_value,
        _utc_datetime_param,
    ) = _import_helpers()
    tokens = _source_tokens(source, config)
    sections = _marketaux_sections(source)
    collected: list[dict[str, object]] = []
    current_token_index = token_index
    section_errors: list[str] = []
    for section_name, section_params in sections:
        section_items, current_token_index, error = _collect_marketaux_section(
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


def collect_akshare_flash(
    source: NewsSourceConfig,
    config: NewsServerConfig | None = None,
    token_index: int = 0,
) -> list[dict[str, object]]:
    """Collect flash or headline news through AKShare."""
    import akshare as ak

    (_MARKETAUX_NEXT_TOKEN_INDEX, _api_params, _int_value, _marketaux_api_params, normalize_items,
     _source_last_success_at, _source_proxy_url, _source_token, _source_tokens,
     _source_next_token_index, _string_value, _utc_datetime_param) = _import_helpers()

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
    records = json.loads(
        dataframe.head(source.limit).to_json(orient="records", force_ascii=False)
    )
    return normalize_items(source.name, provider, records)


def collect_akshare_economic_calendar(
    source: NewsSourceConfig,
    config: NewsServerConfig | None = None,
    token_index: int = 0,
) -> list[dict[str, object]]:
    """Collect macroeconomic calendar events through AKShare/Baidu."""
    import akshare as ak

    (_MARKETAUX_NEXT_TOKEN_INDEX, _api_params, _int_value, _marketaux_api_params, normalize_items,
     _source_last_success_at, _source_proxy_url, _source_token, _source_tokens,
     _source_next_token_index, _string_value, _utc_datetime_param) = _import_helpers()

    date = str(source.params.get("date") or datetime.now().strftime("%Y%m%d"))
    cookie = source.params.get("cookie")
    dataframe = ak.news_economic_baidu(
        date=date,
        cookie=str(cookie) if cookie else None,
    )
    records = json.loads(
        dataframe.head(source.limit).to_json(orient="records", force_ascii=False)
    )
    return normalize_items(source.name, "baidu-economic", records)


def collect_akshare_stock_news(
    source: NewsSourceConfig,
    config: NewsServerConfig | None = None,
    token_index: int = 0,
) -> list[dict[str, object]]:
    """Collect Eastmoney individual stock news through AKShare."""
    import akshare as ak

    (_MARKETAUX_NEXT_TOKEN_INDEX, _api_params, _int_value, _marketaux_api_params, normalize_items,
     _source_last_success_at, _source_proxy_url, _source_token, _source_tokens,
     _source_next_token_index, _string_value, _utc_datetime_param) = _import_helpers()

    symbol = str(source.params.get("symbol") or "")
    if not symbol:
        raise ValueError("akshare_stock source requires symbol")
    dataframe = ak.stock_news_em(symbol=symbol)
    records = json.loads(
        dataframe.head(source.limit).to_json(orient="records", force_ascii=False)
    )
    return normalize_items(source.name, "eastmoney-stock", records)


def collect_akshare_notice(
    source: NewsSourceConfig,
    config: NewsServerConfig | None = None,
    token_index: int = 0,
) -> list[dict[str, object]]:
    """Collect Eastmoney A-share notices through AKShare."""
    import akshare as ak

    (_MARKETAUX_NEXT_TOKEN_INDEX, _api_params, _int_value, _marketaux_api_params, normalize_items,
     _source_last_success_at, _source_proxy_url, _source_token, _source_tokens,
     _source_next_token_index, _string_value, _utc_datetime_param) = _import_helpers()

    kind = str(source.params.get("kind") or source.params.get("symbol") or "重大事项")
    date = str(source.params.get("date") or datetime.now().strftime("%Y%m%d"))
    dataframe = ak.stock_notice_report(symbol=kind, date=date)
    records = json.loads(
        dataframe.head(source.limit).to_json(orient="records", force_ascii=False)
    )
    return normalize_items(source.name, "eastmoney-notice", records)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def _register_builtin_collectors() -> None:
    """Register all built-in collector functions."""
    register_collector("gdelt", collect_gdelt)
    register_collector("marketaux", collect_marketaux)
    register_collector("akshare_flash", collect_akshare_flash)
    register_collector("akshare_economic_calendar", collect_akshare_economic_calendar)
    register_collector("akshare_stock", collect_akshare_stock_news)
    register_collector("akshare_notice", collect_akshare_notice)


# Auto-register on import
_register_builtin_collectors()
