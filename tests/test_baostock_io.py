"""Tests for BaoStock script helpers."""

from __future__ import annotations

from amstock.baostock_io import normalize_baostock_code


def test_normalize_baostock_code() -> None:
    """Common stock code inputs are converted to BaoStock format."""

    assert normalize_baostock_code("600000") == "sh.600000"
    assert normalize_baostock_code("sh600000") == "sh.600000"
    assert normalize_baostock_code("000001") == "sz.000001"
    assert normalize_baostock_code("sz.000001") == "sz.000001"
