"""Twelve Data helpers for US stock quote workflows."""

from __future__ import annotations

import json
import os
from typing import cast
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener, urlopen

from amstock.config import load_settings

TWELVEDATA_API_KEY_ENV = "AMSTOCK_TWELVEDATA_API_KEY"
TWELVEDATA_PROXY_ENV = "AMSTOCK_TWELVEDATA_PROXY"
DEFAULT_TWELVEDATA_BASE_URL = "https://api.twelvedata.com"
DEFAULT_TWELVEDATA_TIMEOUT_SECONDS = 20.0
JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]


def fetch_twelvedata_price(
    *,
    symbol: str,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: float | None = None,
    proxy_url: str | None = None,
) -> dict[str, object]:
    """Fetch the latest price for one US symbol."""

    return _fetch_twelvedata(
        function="price",
        path="/price",
        params={"symbol": normalize_symbol(symbol)},
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        proxy_url=proxy_url,
    )


def fetch_twelvedata_quote(
    *,
    symbol: str,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: float | None = None,
    proxy_url: str | None = None,
) -> dict[str, object]:
    """Fetch a quote snapshot for one US symbol."""

    return _fetch_twelvedata(
        function="quote",
        path="/quote",
        params={"symbol": normalize_symbol(symbol)},
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        proxy_url=proxy_url,
    )


def fetch_twelvedata_quotes(
    *,
    symbols: str,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: float | None = None,
    proxy_url: str | None = None,
) -> dict[str, object]:
    """Fetch quote snapshots for multiple US symbols."""

    normalized = ",".join(split_symbols(symbols))
    return _fetch_twelvedata(
        function="quote",
        path="/quote",
        params={"symbol": normalized},
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        proxy_url=proxy_url,
    )


def fetch_twelvedata_time_series(
    *,
    symbol: str,
    interval: str,
    outputsize: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: float | None = None,
    proxy_url: str | None = None,
) -> dict[str, object]:
    """Fetch historical bars for one US symbol."""

    return _fetch_twelvedata(
        function="time_series",
        path="/time_series",
        params={
            "symbol": normalize_symbol(symbol),
            "interval": interval,
            "outputsize": outputsize,
            "start_date": start_date,
            "end_date": end_date,
        },
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        proxy_url=proxy_url,
    )


def fetch_twelvedata_symbol_search(
    *,
    query: str,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: float | None = None,
    proxy_url: str | None = None,
) -> dict[str, object]:
    """Search Twelve Data symbols."""

    return _fetch_twelvedata(
        function="symbol_search",
        path="/symbol_search",
        params={"symbol": query.strip()},
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        proxy_url=proxy_url,
    )


def _fetch_twelvedata(
    *,
    function: str,
    path: str,
    params: dict[str, object],
    api_key: str | None,
    base_url: str | None,
    timeout: float | None,
    proxy_url: str | None,
) -> dict[str, object]:
    resolved_api_key = resolve_twelvedata_api_key(api_key)
    query_params = clean_params({**params, "apikey": resolved_api_key})
    url = build_url(resolve_twelvedata_base_url(base_url), path, query_params)
    data = request_json(
        url,
        timeout=resolve_twelvedata_timeout(timeout),
        proxy_url=resolve_twelvedata_proxy(proxy_url),
    )
    ensure_twelvedata_success(data)
    public_params = {key: value for key, value in query_params.items() if key != "apikey"}
    rows, returned_rows = row_counts(data)
    return {
        "ok": True,
        "source": "twelvedata",
        "function": function,
        "params": public_params,
        "rows": rows,
        "returned_rows": returned_rows,
        "data": data,
        "url": redact_query(url, keys=("apikey",)),
    }


def resolve_twelvedata_api_key(value: str | None = None) -> str:
    """Resolve the Twelve Data API key from option, environment, or config."""

    if value and value.strip():
        return value.strip()
    env_value = os.environ.get(TWELVEDATA_API_KEY_ENV)
    if env_value and env_value.strip():
        return env_value.strip()
    try:
        config_value = load_settings().twelvedata_api_key
    except Exception:
        config_value = ""
    if config_value.strip():
        return config_value.strip()
    msg = (
        "Twelve Data API key is required; pass --api-key, set "
        f"{TWELVEDATA_API_KEY_ENV}, or configure credentials.twelvedata.api_key"
    )
    raise ValueError(msg)


def resolve_twelvedata_base_url(value: str | None = None) -> str:
    """Resolve the Twelve Data base URL."""

    if value and value.strip():
        return value.strip()
    try:
        config_value = load_settings().twelvedata_base_url
    except Exception:
        config_value = ""
    return config_value.strip() or DEFAULT_TWELVEDATA_BASE_URL


def resolve_twelvedata_timeout(value: float | None = None) -> float:
    """Resolve the Twelve Data HTTP timeout."""

    if value is not None:
        return value
    try:
        config_value = load_settings().twelvedata_timeout
    except Exception:
        config_value = DEFAULT_TWELVEDATA_TIMEOUT_SECONDS
    return config_value


def resolve_twelvedata_proxy(value: str | None = None) -> str | None:
    """Resolve an optional Twelve Data HTTP proxy URL."""

    if value is not None:
        return value.strip() or None
    env_value = os.environ.get(TWELVEDATA_PROXY_ENV)
    if env_value and env_value.strip():
        return env_value.strip()
    try:
        config_value = load_settings().twelvedata_proxy_url
    except Exception:
        config_value = ""
    return config_value.strip() or None


def request_json(
    url: str,
    *,
    timeout: float,
    proxy_url: str | None = None,
) -> JsonValue:
    """Request a Twelve Data URL and parse JSON."""

    request = Request(url, headers={"User-Agent": "AMStock/0.1"})
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
        msg = "Twelve Data response was not valid JSON"
        raise ValueError(msg) from exc


def ensure_twelvedata_success(data: JsonValue) -> None:
    """Raise a ValueError when Twelve Data returns an API error payload."""

    if not isinstance(data, dict):
        return
    status = data.get("status")
    if status in {"error", "ERROR"}:
        message = data.get("message")
        code = data.get("code")
        details = str(message) if message else "Twelve Data API request failed"
        if code is not None:
            details = f"{details} (code={code})"
        raise ValueError(details)


def clean_params(params: dict[str, object]) -> dict[str, object]:
    """Drop empty query parameters."""

    cleaned: dict[str, object] = {}
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        cleaned[key] = value
    return cleaned


def build_url(base_url: str, path: str, params: dict[str, object]) -> str:
    """Build a GET URL."""

    base = base_url.rstrip("/")
    query = urlencode(params)
    return f"{base}{path}" if not query else f"{base}{path}?{query}"


def redact_query(url: str, *, keys: tuple[str, ...]) -> str:
    """Redact sensitive query parameter values from a URL."""

    redacted = url
    for key in keys:
        marker = f"{key}="
        if marker not in redacted:
            continue
        prefix, suffix = redacted.split(marker, 1)
        value, separator, rest = suffix.partition("&")
        _ = value
        redacted = f"{prefix}{marker}***{separator}{rest}"
    return redacted


def split_symbols(value: str) -> list[str]:
    """Split and normalize a comma-separated symbol list."""

    symbols = [normalize_symbol(item) for item in value.split(",") if item.strip()]
    if not symbols:
        msg = "at least one symbol is required"
        raise ValueError(msg)
    return symbols


def normalize_symbol(value: str) -> str:
    """Normalize a US stock symbol."""

    symbol = value.strip().upper()
    if not symbol:
        msg = "symbol is required"
        raise ValueError(msg)
    return symbol


def row_counts(data: JsonValue) -> tuple[int | None, int | None]:
    """Return total and returned rows when the response has list-like records."""

    if isinstance(data, dict):
        if isinstance(data.get("values"), list):
            count = len(data["values"])
            return count, count
        if isinstance(data.get("data"), list):
            count = len(data["data"])
            return count, count
        if is_batch_response(data):
            count = len(data)
            return count, count
        return 1, 1
    if isinstance(data, list):
        count = len(data)
        return count, count
    return None, None


def is_batch_response(data: dict[str, JsonValue]) -> bool:
    """Return whether a response looks like a multi-symbol Twelve Data payload."""

    if not data:
        return False
    meta_keys = {"status", "message", "code"}
    return not set(data).issubset(meta_keys) and all(
        isinstance(value, dict) for value in data.values()
    )
