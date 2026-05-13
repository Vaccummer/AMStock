"""Helpers for AKShare command scripts."""

from __future__ import annotations

import json
import os
import socket
from http.client import RemoteDisconnected
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse

    import pandas as pd


def dataframe_payload(
    function: str,
    params: dict[str, object],
    dataframe: pd.DataFrame,
    *,
    limit: int | None = None,
) -> dict[str, object]:
    """Build a JSON-serializable payload from a pandas DataFrame."""

    limited = dataframe.head(limit) if limit is not None else dataframe
    records = json.loads(limited.to_json(orient="records", force_ascii=False, date_format="iso"))
    return {
        "ok": True,
        "source": "akshare",
        "function": function,
        "params": params,
        "rows": len(dataframe),
        "returned_rows": len(limited),
        "columns": [str(column) for column in dataframe.columns],
        "data": records,
    }


def error_payload(error: Exception) -> dict[str, object]:
    """Build a JSON-serializable error payload."""

    return {
        "ok": False,
        "error": {
            "type": type(error).__name__,
            "message": str(error),
        },
    }


def is_connection_error(error: Exception) -> bool:
    """Return whether an exception looks like a transient network failure."""

    connection_error_names = {
        "ConnectionError",
        "ConnectTimeout",
        "HTTPError",
        "ProxyError",
        "ReadTimeout",
        "RemoteDisconnected",
        "Timeout",
    }
    current: BaseException | None = error
    while current is not None:
        if type(current).__name__ in connection_error_names:
            return True
        if isinstance(current, (TimeoutError, ConnectionError, RemoteDisconnected)):
            return True
        current = current.__cause__ or current.__context__
    return False


def add_fallback_metadata(
    payload: dict[str, object],
    *,
    function: str,
    error: Exception,
) -> dict[str, object]:
    """Mark a payload as a fallback response."""

    payload["fallback_from"] = {
        "source": "akshare",
        "function": function,
        "error": {
            "type": type(error).__name__,
            "message": str(error),
        },
    }
    return payload


def emit_json(payload: dict[str, object]) -> None:
    """Print a JSON payload for agent consumption."""

    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def add_network_options(parser: argparse.ArgumentParser) -> None:
    """Add common network flags to an argparse parser."""

    parser.add_argument(
        "--no-proxy",
        action="store_true",
        help="Disable HTTP proxy environment variables for this run.",
    )
    parser.add_argument(
        "--ipv4",
        action="store_true",
        help="Force IPv4 DNS resolution for AKShare requests.",
    )


def configure_network(*, no_proxy: bool = False, ipv4: bool = False) -> None:
    """Apply process-local network options before importing AKShare."""

    if no_proxy:
        for name in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
        ):
            os.environ.pop(name, None)
        os.environ["NO_PROXY"] = "*"

    if ipv4:
        import urllib3.util.connection

        urllib3.util.connection.allowed_gai_family = lambda: socket.AF_INET


def normalize_a_stock_code(symbol: str) -> str:
    """Return a six-digit A-share code without exchange prefix."""

    normalized = symbol.lower().removeprefix("sh").removeprefix("sz").removeprefix("bj")
    if not normalized.isdigit() or len(normalized) != 6:
        msg = f"expected a 6-digit A-share symbol, got {symbol!r}"
        raise ValueError(msg)
    return normalized


def sina_stock_code(symbol: str) -> str:
    """Return a Sina-style stock code like sh600519 or sz000001."""

    normalized = normalize_a_stock_code(symbol)
    if normalized.startswith(("6", "9")):
        return f"sh{normalized}"
    if normalized.startswith(("0", "2", "3")):
        return f"sz{normalized}"
    if normalized.startswith(("4", "8")):
        return f"bj{normalized}"

    msg = f"cannot infer exchange prefix for {symbol!r}"
    raise ValueError(msg)
