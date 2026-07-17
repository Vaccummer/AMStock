"""Parse complete market-snapshot text exports into typed records."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from amstock.exceptions import ValidationError

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class MarketSnapshotInput:
    """One market-snapshot row with source units expanded to base units."""

    stock_code: str
    stock_name: str
    industry: str
    latest: Decimal | None
    change_percent: Decimal | None
    change_amount: Decimal | None
    total_volume: Decimal | None
    current_volume: Decimal | None
    bid_price: Decimal | None
    ask_price: Decimal | None
    speed_percent: Decimal | None
    turnover_percent: Decimal | None
    amount_yuan: Decimal | None
    dynamic_pe: Decimal | None
    high: Decimal | None
    low: Decimal | None
    open_price: Decimal | None
    previous_close: Decimal | None
    amplitude_percent: Decimal | None
    volume_ratio: Decimal | None
    order_ratio_percent: Decimal | None
    order_difference: Decimal | None
    average_price: Decimal | None
    inner_volume: Decimal | None
    outer_volume: Decimal | None
    inner_outer_ratio: Decimal | None
    bid_one_volume: Decimal | None
    ask_one_volume: Decimal | None
    pb: Decimal | None
    total_shares: Decimal | None
    total_market_cap_yuan: Decimal | None
    circulating_shares: Decimal | None
    circulating_market_cap_yuan: Decimal | None
    change_3d_percent: Decimal | None
    change_6d_percent: Decimal | None
    turnover_3d_percent: Decimal | None
    turnover_6d_percent: Decimal | None
    consecutive_up_days: Decimal | None
    month_change_percent: Decimal | None
    year_change_percent: Decimal | None
    one_month_change_percent: Decimal | None
    one_year_change_percent: Decimal | None


_REQUIRED_HEADINGS = (
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
_TEXT_FIELDS = (
    ("stock_code", "代码"),
    ("stock_name", "名称"),
    ("industry", "所属行业"),
)
_NUMERIC_FIELDS = (
    ("latest", "最新"),
    ("change_percent", "涨幅%"),
    ("change_amount", "涨跌"),
    ("total_volume", "总量"),
    ("current_volume", "现量"),
    ("bid_price", "买入价"),
    ("ask_price", "卖出价"),
    ("speed_percent", "涨速%"),
    ("turnover_percent", "换手%"),
    ("amount_yuan", "金额"),
    ("dynamic_pe", "市盈率(动)"),
    ("high", "最高"),
    ("low", "最低"),
    ("open_price", "开盘"),
    ("previous_close", "昨收"),
    ("amplitude_percent", "振幅%"),
    ("volume_ratio", "量比"),
    ("order_ratio_percent", "委比%"),
    ("order_difference", "委差"),
    ("average_price", "均价"),
    ("inner_volume", "内盘"),
    ("outer_volume", "外盘"),
    ("inner_outer_ratio", "内外比"),
    ("bid_one_volume", "买一量"),
    ("ask_one_volume", "卖一量"),
    ("pb", "市净率"),
    ("total_shares", "总股本"),
    ("total_market_cap_yuan", "总市值"),
    ("circulating_shares", "流通股本"),
    ("circulating_market_cap_yuan", "流通市值"),
    ("change_3d_percent", "3日涨幅%"),
    ("change_6d_percent", "6日涨幅%"),
    ("turnover_3d_percent", "3日换手%"),
    ("turnover_6d_percent", "6日换手%"),
    ("consecutive_up_days", "连涨天数"),
    ("month_change_percent", "本月涨幅%"),
    ("year_change_percent", "今年涨幅%"),
    ("one_month_change_percent", "近一月涨幅%"),
    ("one_year_change_percent", "近一年涨幅%"),
)
_SCALED_DECIMAL = re.compile(r"([+-]?\d+(?:\.\d+)?)(万亿|万|亿)?")


def parse_market_snapshot_file(path: Path) -> list[MarketSnapshotInput]:
    """Decode and validate a complete market-snapshot export."""

    lines = [
        (line_number, line)
        for line_number, line in enumerate(_read_text(path).splitlines(), start=1)
        if line.strip()
    ]
    if not lines:
        raise ValidationError("line 1: missing header")

    header_line_number, header = lines[0]
    _validate_header(_cells(header), line_number=header_line_number)
    records: list[MarketSnapshotInput] = []
    stock_codes: set[str] = set()
    for line_number, line in lines[1:]:
        record = _parse_row(_cells(line), line_number=line_number)
        if record.stock_code in stock_codes:
            raise ValidationError(
                f"line {line_number}: duplicate stock code: {record.stock_code}"
            )
        stock_codes.add(record.stock_code)
        records.append(record)
    return records


def parse_scaled_decimal(
    value: str, *, line_number: int, nullable: bool = False
) -> Decimal | None:
    """Parse a finite decimal and expand a supported Chinese scale suffix."""

    stripped = value.strip()
    if stripped == "—":
        if nullable:
            return None
        raise ValidationError(f"line {line_number}: invalid numeric value: {value}")
    match = _SCALED_DECIMAL.fullmatch(stripped)
    if match is None:
        raise ValidationError(f"line {line_number}: invalid numeric value: {value}")
    multiplier = {
        None: Decimal("1"),
        "万": Decimal("10000"),
        "亿": Decimal("100000000"),
        "万亿": Decimal("1000000000000"),
    }[match.group(2)]
    decimal = Decimal(match.group(1)) * multiplier
    if not decimal.is_finite():
        raise ValidationError(f"line {line_number}: invalid numeric value: {value}")
    return decimal


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8", "gb18030", "gbk"):
        try:
            return raw.decode(encoding, errors="strict")
        except UnicodeDecodeError:
            continue
    raise ValidationError(f"line 1: unable to decode market snapshot file: {path}")


def _validate_header(cells: list[str], *, line_number: int) -> None:
    seen: set[str] = set()
    for cell in cells:
        if cell in seen:
            raise ValidationError(f"line {line_number}: duplicate column: {cell}")
        seen.add(cell)
    unknown = [cell for cell in cells if cell not in _REQUIRED_HEADINGS]
    if unknown:
        raise ValidationError(f"line {line_number}: unknown column: {unknown[0]}")
    missing = [heading for heading in _REQUIRED_HEADINGS if heading not in seen]
    if missing:
        raise ValidationError(
            f"line {line_number}: missing required column: {missing[0]}"
        )
    if tuple(cells) != _REQUIRED_HEADINGS:
        raise ValidationError(f"line {line_number}: columns are not in the required order")


def _parse_row(cells: list[str], *, line_number: int) -> MarketSnapshotInput:
    if len(cells) > len(_REQUIRED_HEADINGS):
        surplus = len(cells) - len(_REQUIRED_HEADINGS)
        stock_name_end = 3 + surplus
        cells = [*cells[:2], "".join(cells[2:stock_name_end]), *cells[stock_name_end:]]
    if len(cells) != len(_REQUIRED_HEADINGS):
        raise ValidationError(
            f"line {line_number}: expected {len(_REQUIRED_HEADINGS)} columns, got {len(cells)}"
        )
    values = dict(zip(_REQUIRED_HEADINGS, cells, strict=True))
    text_values = {field: values[heading] for field, heading in _TEXT_FIELDS}
    numeric_values = {
        field: parse_scaled_decimal(
            values[heading], line_number=line_number, nullable=True
        )
        for field, heading in _NUMERIC_FIELDS
    }
    return MarketSnapshotInput(**text_values, **numeric_values)


def _cells(line: str) -> list[str]:
    return re.split(r"\s+", line.strip())
