"""Tests for the complete market-snapshot text parser."""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from amstock.exceptions import ValidationError
from amstock.market_snapshot_io import parse_market_snapshot_file, parse_scaled_decimal

if TYPE_CHECKING:
    from pathlib import Path


HEADINGS = (
    "序",
    "代码",
    "名称",
    "最新",
    "涨幅%",
    "涨跌",
    "总量",
    "现量",
    "买入价",
    "卖出价",
    "涨速%",
    "换手%",
    "金额",
    "市盈率(动)",
    "所属行业",
    "最高",
    "最低",
    "开盘",
    "昨收",
    "振幅%",
    "量比",
    "委比%",
    "委差",
    "均价",
    "内盘",
    "外盘",
    "内外比",
    "买一量",
    "卖一量",
    "市净率",
    "总股本",
    "总市值",
    "流通股本",
    "流通市值",
    "3日涨幅%",
    "6日涨幅%",
    "3日换手%",
    "6日换手%",
    "连涨天数",
    "本月涨幅%",
    "今年涨幅%",
    "近一月涨幅%",
    "近一年涨幅%",
)
ROW_ONE = (
    "1 300577 开润股份 20.36 19.98 3.39 1.04万 1.04万 20.36 — 0.00 0.73 "
    "2121万 12.36 服装家纺 20.36 20.36 20.36 16.97 0.00 107.08 100.00 27.9万 "
    "20.36 1.04万 0 1.00 27.9万 0 2.30 2.398亿 48.83亿 1.422亿 28.94亿 22.95 "
    "22.65 5.64 8.94 1 39.36 -3.55 33.95 2.67"
)
ROW_TWO = (
    "4 003001 中岩大地 19.56 10.01 1.78 1.03万 1.03万 19.55 19.56 0.00 0.90 "
    "2021万 129.04 专业工程 19.56 19.56 19.56 17.78 0.00 17.28 -99.44 -3889 "
    "19.56 6574 3759 1.75 1 3900 2.89 1.746亿 34.14亿 1.144亿 22.37亿 20.74 "
    "51.39 27.45 63.63 8 51.04 -2.44 37.46 -27.93"
)
SAMPLE = "\n".join((" ".join(HEADINGS), ROW_ONE, ROW_TWO))


def write_sample(path: Path, text: str = SAMPLE) -> None:
    path.write_bytes(text.encode("gb18030"))


def test_parse_scaled_decimal_converts_supported_units_and_nullable_placeholder() -> None:
    assert parse_scaled_decimal("1.04万", line_number=2) == Decimal("10400")
    assert parse_scaled_decimal("2.398亿", line_number=2) == Decimal("239800000")
    assert parse_scaled_decimal("—", line_number=2, nullable=True) is None


def test_parse_scaled_decimal_converts_wanyi_used_by_source_export() -> None:
    assert parse_scaled_decimal("1.72万亿", line_number=132) == Decimal("1720000000000")


def test_parse_market_snapshot_maps_every_business_heading(tmp_path: Path) -> None:
    path = tmp_path / "snapshot.txt"
    write_sample(path)

    records = parse_market_snapshot_file(path)

    assert len(records) == 2
    assert asdict(records[0]) == {
        "stock_code": "300577",
        "stock_name": "开润股份",
        "industry": "服装家纺",
        "latest": Decimal("20.36"),
        "change_percent": Decimal("19.98"),
        "change_amount": Decimal("3.39"),
        "total_volume": Decimal("10400"),
        "current_volume": Decimal("10400"),
        "bid_price": Decimal("20.36"),
        "ask_price": None,
        "speed_percent": Decimal("0.00"),
        "turnover_percent": Decimal("0.73"),
        "amount_yuan": Decimal("21210000"),
        "dynamic_pe": Decimal("12.36"),
        "high": Decimal("20.36"),
        "low": Decimal("20.36"),
        "open_price": Decimal("20.36"),
        "previous_close": Decimal("16.97"),
        "amplitude_percent": Decimal("0.00"),
        "volume_ratio": Decimal("107.08"),
        "order_ratio_percent": Decimal("100.00"),
        "order_difference": Decimal("279000"),
        "average_price": Decimal("20.36"),
        "inner_volume": Decimal("10400"),
        "outer_volume": Decimal("0"),
        "inner_outer_ratio": Decimal("1.00"),
        "bid_one_volume": Decimal("279000"),
        "ask_one_volume": Decimal("0"),
        "pb": Decimal("2.30"),
        "total_shares": Decimal("239800000"),
        "total_market_cap_yuan": Decimal("4883000000"),
        "circulating_shares": Decimal("142200000"),
        "circulating_market_cap_yuan": Decimal("2894000000"),
        "change_3d_percent": Decimal("22.95"),
        "change_6d_percent": Decimal("22.65"),
        "turnover_3d_percent": Decimal("5.64"),
        "turnover_6d_percent": Decimal("8.94"),
        "consecutive_up_days": Decimal("1"),
        "month_change_percent": Decimal("39.36"),
        "year_change_percent": Decimal("-3.55"),
        "one_month_change_percent": Decimal("33.95"),
        "one_year_change_percent": Decimal("2.67"),
    }
    assert records[1].stock_code == "003001"


def test_parse_market_snapshot_joins_source_stock_name_with_internal_spaces(
    tmp_path: Path,
) -> None:
    path = tmp_path / "snapshot.txt"
    write_sample(path, SAMPLE.replace("开润股份", "开 润 股 份", 1))

    records = parse_market_snapshot_file(path)

    assert records[0].stock_name == "开润股份"


@pytest.mark.parametrize(
    ("malformed_prefix", "message"),
    (
        ("1 300 577", r"line 3.*invalid stock code.*300"),
        ("row 300577", r"line 3.*invalid sequence.*row"),
    ),
)
def test_parse_market_snapshot_rejects_malformed_prefix_before_joining_name(
    tmp_path: Path, malformed_prefix: str, message: str
) -> None:
    path = tmp_path / "snapshot.txt"
    malformed = SAMPLE.replace("\n1 300577", f"\n\n{malformed_prefix}", 1)
    write_sample(path, malformed)

    with pytest.raises(ValidationError, match=message):
        parse_market_snapshot_file(path)


def test_all_numeric_metrics_accept_source_placeholder(tmp_path: Path) -> None:
    path = tmp_path / "snapshot.txt"
    cells = ROW_ONE.split()
    cells[3:] = [*(["—"] * 11), cells[14], *(["—"] * 28)]
    write_sample(path, "\n".join((" ".join(HEADINGS), " ".join(cells))))

    [record] = parse_market_snapshot_file(path)

    values = asdict(record)
    numeric_values = {
        key: value
        for key, value in values.items()
        if key not in {"stock_code", "stock_name", "industry"}
    }
    assert numeric_values and set(numeric_values.values()) == {None}


@pytest.mark.parametrize("value", ["1千", "1万元", "--1", "NaN", "Infinity"])
def test_parse_scaled_decimal_rejects_malformed_or_non_finite_values(value: str) -> None:
    with pytest.raises(ValidationError, match=r"line 7.*invalid numeric value"):
        parse_scaled_decimal(value, line_number=7)


def test_bad_unit_reports_physical_line_after_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "snapshot.txt"
    malformed = SAMPLE.replace("\n" + ROW_ONE, "\n\n" + ROW_ONE).replace(
        "1.04万", "1.04千", 1
    )
    write_sample(path, malformed)

    with pytest.raises(ValidationError, match=r"line 3.*invalid numeric value.*1.04千"):
        parse_market_snapshot_file(path)


def test_duplicate_stock_code_reports_physical_line(tmp_path: Path) -> None:
    path = tmp_path / "snapshot.txt"
    write_sample(path, SAMPLE.replace("4 003001", "4 300577"))

    with pytest.raises(ValidationError, match=r"line 3.*duplicate stock code.*300577"):
        parse_market_snapshot_file(path)


@pytest.mark.parametrize(
    ("header", "message"),
    (
        (" ".join(HEADINGS).replace(" 代码", "", 1), r"line 4.*missing required column.*代码"),
        (" ".join((*HEADINGS, "未知列")), r"line 4.*unknown column.*未知列"),
        (" ".join((HEADINGS[0], HEADINGS[1], *HEADINGS[1:])), r"line 4.*duplicate column.*代码"),
    ),
)
def test_invalid_headers_report_physical_line(tmp_path: Path, header: str, message: str) -> None:
    path = tmp_path / "snapshot.txt"
    write_sample(path, "\n\n\n" + "\n".join((header, ROW_ONE)))

    with pytest.raises(ValidationError, match=message):
        parse_market_snapshot_file(path)
