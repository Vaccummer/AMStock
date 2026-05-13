"""Helpers for BaoStock command scripts."""

from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from io import StringIO
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator


def emit_json(payload: dict[str, object]) -> None:
    """Print a JSON payload for agent consumption."""

    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def error_payload(error: Exception) -> dict[str, object]:
    """Build a JSON-serializable error payload."""

    return {
        "ok": False,
        "error": {
            "type": type(error).__name__,
            "message": str(error),
        },
    }


def normalize_baostock_code(symbol: str) -> str:
    """Return a BaoStock code like sh.600000 or sz.000001."""

    value = symbol.strip().lower()
    if value.startswith(("sh.", "sz.", "bj.")):
        return value

    value = value.removeprefix("sh").removeprefix("sz").removeprefix("bj")
    if not value.isdigit() or len(value) != 6:
        msg = f"expected a 6-digit stock code, got {symbol!r}"
        raise ValueError(msg)

    if value.startswith(("5", "6", "9")):
        return f"sh.{value}"
    return f"sz.{value}"


@contextmanager
def suppress_stdout() -> Iterator[None]:
    """Suppress libraries that print status text to stdout."""

    original_stdout = sys.stdout
    sys.stdout = StringIO()
    try:
        yield
    finally:
        sys.stdout = original_stdout


@contextmanager
def baostock_session() -> Iterator[object]:
    """Login to BaoStock and logout when done."""

    import baostock as bs

    with suppress_stdout():
        login_result = bs.login()
    if login_result.error_code != "0":
        msg = f"baostock login failed: {login_result.error_msg}"
        raise RuntimeError(msg)

    try:
        yield bs
    finally:
        with suppress_stdout():
            bs.logout()


def result_set_payload(
    function: str,
    params: dict[str, object],
    result_set: object,
    *,
    limit: int | None = None,
) -> dict[str, object]:
    """Convert a BaoStock result set to a JSON payload."""

    error_code = getattr(result_set, "error_code", "")
    error_msg = getattr(result_set, "error_msg", "")
    if error_code != "0":
        msg = f"{function} failed: {error_msg}"
        raise RuntimeError(msg)

    fields = [str(field) for field in getattr(result_set, "fields", [])]
    rows: list[dict[str, str]] = []
    total_seen = 0
    while result_set.next():
        total_seen += 1
        rows.append(dict(zip(fields, result_set.get_row_data(), strict=True)))
        if limit is not None and len(rows) >= limit:
            break

    return {
        "ok": True,
        "source": "baostock",
        "function": function,
        "params": params,
        "rows_seen": total_seen,
        "truncated": limit is not None and len(rows) >= limit,
        "returned_rows": len(rows),
        "columns": fields,
        "data": rows,
    }
