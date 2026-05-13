"""Tests for AKShare script helpers."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pandas as pd

from amstock.akshare_io import (
    dataframe_payload,
    emit_json,
    normalize_a_stock_code,
    sina_stock_code,
)

if TYPE_CHECKING:
    import pytest


def test_dataframe_payload_limits_records() -> None:
    """DataFrame payloads include metadata and a limited record sample."""

    dataframe = pd.DataFrame(
        [
            {"代码": "600519", "名称": "贵州茅台"},
            {"代码": "000001", "名称": "平安银行"},
        ]
    )

    payload = dataframe_payload("example", {"symbol": "600519"}, dataframe, limit=1)

    assert payload["ok"] is True
    assert payload["rows"] == 2
    assert payload["returned_rows"] == 1
    assert payload["columns"] == ["代码", "名称"]
    assert payload["data"] == [{"代码": "600519", "名称": "贵州茅台"}]


def test_emit_json_preserves_chinese(capsys: pytest.CaptureFixture[str]) -> None:
    """JSON output is machine-readable and does not escape Chinese text."""

    emit_json({"ok": True, "名称": "贵州茅台"})

    captured = capsys.readouterr().out
    assert "贵州茅台" in captured
    assert json.loads(captured) == {"ok": True, "名称": "贵州茅台"}


def test_a_share_symbol_helpers() -> None:
    """A-share helpers normalize common symbol forms."""

    assert normalize_a_stock_code("sh600519") == "600519"
    assert normalize_a_stock_code("SZ000001") == "000001"
    assert sina_stock_code("600519") == "sh600519"
    assert sina_stock_code("000001") == "sz000001"
