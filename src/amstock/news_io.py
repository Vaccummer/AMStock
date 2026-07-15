"""News API helpers for agent-facing market intelligence workflows."""

from __future__ import annotations

import json
import os
from typing import cast
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener, urlopen

from amstock.config import load_settings

GDELT_TOKEN_ENV = "AMSTOCK_GDELT_CLOUD_TOKEN"
MARKETAUX_TOKEN_ENV = "AMSTOCK_MARKETAUX_TOKEN"
NEWS_PROXY_ENV = "AMSTOCK_NEWS_PROXY"
DEFAULT_GDELT_BASE_URL = "https://gdeltcloud.com"
DEFAULT_MARKETAUX_BASE_URL = "https://api.marketaux.com"
DEFAULT_NEWS_TIMEOUT_SECONDS = 20.0
JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]


def fetch_gdelt_news(
    *,
    endpoint: str,
    params: dict[str, object],
    token_value: str | None = None,
    base_url: str = DEFAULT_GDELT_BASE_URL,
    timeout: float = DEFAULT_NEWS_TIMEOUT_SECONDS,
    limit: int | None = None,
    proxy_url: str | None = None,
) -> dict[str, object]:
    """Fetch GDELT Cloud news events/stories and return AMStock JSON."""

    token = resolve_gdelt_token(token_value)
    endpoint_path = gdelt_endpoint_path(endpoint)
    query_params = clean_params(
        {**params, "limit": limit if limit is not None else params.get("limit")}
    )
    url = build_url(base_url, endpoint_path, query_params)
    data = request_json(
        url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout,
        proxy_url=resolve_news_proxy(proxy_url),
    )
    records = gdelt_records(data)
    returned_rows = len(records) if records is not None else None
    return {
        "ok": True,
        "source": "gdelt-cloud",
        "function": f"gdelt-{endpoint}",
        "params": query_params,
        "rows": returned_rows,
        "returned_rows": returned_rows,
        "data": data,
        "url": redact_query(url, keys=("api_token",)),
    }


def fetch_marketaux_news(
    *,
    params: dict[str, object],
    token_value: str | None = None,
    base_url: str = DEFAULT_MARKETAUX_BASE_URL,
    timeout: float = DEFAULT_NEWS_TIMEOUT_SECONDS,
    limit: int | None = None,
    proxy_url: str | None = None,
) -> dict[str, object]:
    """Fetch Marketaux financial news and return AMStock JSON."""

    token = resolve_marketaux_token(token_value)
    query_params = clean_params(
        {**params, "limit": limit if limit is not None else params.get("limit"), "api_token": token}
    )
    url = build_url(base_url, "/v1/news/all", query_params)
    data = request_json(url, timeout=timeout, proxy_url=resolve_news_proxy(proxy_url))
    rows, returned_rows = marketaux_row_counts(data)
    public_params = {key: value for key, value in query_params.items() if key != "api_token"}
    return {
        "ok": True,
        "source": "marketaux",
        "function": "marketaux-news-all",
        "params": public_params,
        "rows": rows,
        "returned_rows": returned_rows,
        "data": data,
        "url": redact_query(url, keys=("api_token",)),
    }


def resolve_gdelt_token(value: str | None = None) -> str:
    """Resolve a GDELT Cloud token from an option, environment, or config."""

    return resolve_news_tokens(
        value,
        env_name=GDELT_TOKEN_ENV,
        config_attrs=("gdelt_cloud_tokens", "gdelt_cloud_token"),
        label="GDELT Cloud token",
    )[0]


def resolve_marketaux_token(value: str | None = None) -> str:
    """Resolve a Marketaux token from an option, environment, or config."""

    return resolve_news_tokens(
        value,
        env_name=MARKETAUX_TOKEN_ENV,
        config_attrs=("marketaux_tokens", "marketaux_token"),
        label="Marketaux token",
    )[0]


def resolve_news_tokens(
    value: str | None,
    *,
    env_name: str,
    config_attrs: tuple[str, ...],
    label: str,
) -> tuple[str, ...]:
    """Resolve one or more news API tokens."""

    if value and value.strip():
        return tuple(token for token in split_token_values(value) if token)
    env_value = os.environ.get(env_name)
    if env_value and env_value.strip():
        return tuple(token for token in split_token_values(env_value) if token)
    try:
        settings = load_settings()
    except Exception:
        settings = None
    if settings is not None:
        for config_attr in config_attrs:
            config_value = getattr(settings, config_attr)
            if isinstance(config_value, tuple) and config_value:
                return config_value
            if isinstance(config_value, str) and config_value.strip():
                return tuple(split_token_values(config_value))
    msg = f"{label} is required; pass --token, set {env_name}, or configure credentials.news"
    raise ValueError(msg)


def split_token_values(value: str) -> list[str]:
    """Split comma-separated token strings."""

    return [item.strip() for item in value.split(",") if item.strip()]


def resolve_news_proxy(value: str | None = None) -> str | None:
    """Resolve the news HTTP proxy URL from option, environment, or config."""

    if value is not None:
        return value.strip() or None
    env_value = os.environ.get(NEWS_PROXY_ENV)
    if env_value and env_value.strip():
        return env_value.strip()
    try:
        config_value = load_settings().news_proxy_url
    except Exception:
        config_value = ""
    return config_value.strip() or None


def gdelt_endpoint_path(endpoint: str) -> str:
    """Return the GDELT API path for a supported endpoint."""

    paths = {
        "stories": "/api/v2/stories",
        "events": "/api/v2/events",
        "media-events": "/api/v1/media-events",
    }
    try:
        return paths[endpoint]
    except KeyError as exc:
        choices = ", ".join(sorted(paths))
        msg = f"unsupported GDELT endpoint {endpoint!r}; choose one of: {choices}"
        raise ValueError(msg) from exc


def clean_params(params: dict[str, object]) -> dict[str, object]:
    """Drop empty values and encode booleans as API-friendly strings."""

    cleaned: dict[str, object] = {}
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, bool):
            cleaned[key] = "true" if value else "false"
        else:
            cleaned[key] = value
    return cleaned


def build_url(base_url: str, path: str, params: dict[str, object]) -> str:
    """Build a GET URL."""

    base = base_url.rstrip("/")
    query = urlencode(params)
    return f"{base}{path}" if not query else f"{base}{path}?{query}"


def request_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = DEFAULT_NEWS_TIMEOUT_SECONDS,
    proxy_url: str | None = None,
) -> JsonValue:
    """Request a URL and parse JSON."""

    request = Request(url, headers={"User-Agent": "AMStock/0.1", **(headers or {})})
    if proxy_url:
        opener = build_opener(ProxyHandler({"http": proxy_url, "https": proxy_url}))
        response_context = opener.open(request, timeout=timeout)
    else:
        response_context = urlopen(request, timeout=timeout)
    with response_context as response:
        raw = response.read().decode("utf-8-sig")
    try:
        return cast("JsonValue", json.loads(raw))
    except json.JSONDecodeError as exc:
        msg = "news API response was not valid JSON"
        raise ValueError(msg) from exc


def gdelt_records(data: JsonValue) -> list[object] | None:
    """Return the list-like payload from a GDELT response when available."""

    if not isinstance(data, dict):
        return None
    for key in ("data", "clusters", "events", "stories"):
        value = data.get(key)
        if isinstance(value, list):
            return value
    return None


def marketaux_row_counts(data: JsonValue) -> tuple[int | None, int | None]:
    """Return total and returned rows from a Marketaux response."""

    if not isinstance(data, dict):
        return None, None
    records = data.get("data")
    returned = len(records) if isinstance(records, list) else None
    meta = data.get("meta")
    if isinstance(meta, dict):
        found = meta.get("found")
        if isinstance(found, int):
            return found, returned
    return returned, returned


def redact_query(url: str, *, keys: tuple[str, ...]) -> str:
    """Redact query-string secrets for payload metadata."""

    redacted = url
    for key in keys:
        if f"{key}=" not in redacted:
            continue
        prefix, rest = redacted.split(f"{key}=", 1)
        suffix = rest.split("&", 1)
        redacted = f"{prefix}{key}=***" + (f"&{suffix[1]}" if len(suffix) == 2 else "")
    return redacted
