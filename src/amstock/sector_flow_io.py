"""Parse board-sector capital-flow text exports into validated records."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from amstock.exceptions import ValidationError

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class SectorFlowInput:
    """One validated sector-flow row, with every amount expressed in yuan."""

    sector_code: str
    sector_name: str
    latest: Decimal
    change_percent: Decimal
    main_net_inflow_yuan: Decimal
    auction_yuan: Decimal
    super_order_inflow_yuan: Decimal
    super_order_outflow_yuan: Decimal
    super_order_net_yuan: Decimal
    super_order_net_ratio: Decimal
    large_order_inflow_yuan: Decimal
    large_order_outflow_yuan: Decimal
    large_order_net_yuan: Decimal
    large_order_net_ratio: Decimal
    medium_order_inflow_yuan: Decimal
    medium_order_outflow_yuan: Decimal
    medium_order_net_yuan: Decimal
    medium_order_net_ratio: Decimal
    small_order_inflow_yuan: Decimal
    small_order_outflow_yuan: Decimal
    small_order_net_yuan: Decimal
    small_order_net_ratio: Decimal


_REQUIRED_HEADINGS = (
    "序",
    "代码",
    "名称",
    "最新",
    "涨幅%",
    "主力净流入",
    "集合竞价",
    "超大单流入",
    "超大单流出",
    "超大单净额",
    "超大单净占比",
    "大单流入",
    "大单流出",
    "大单净额",
    "大单净占比",
    "中单流入",
    "中单流出",
    "中单净额",
    "中单净占比",
    "小单流入",
    "小单流出",
    "小单净额",
    "小单净占比",
)
_MONEY_FIELDS = (
    ("main_net_inflow_yuan", "主力净流入"),
    ("auction_yuan", "集合竞价"),
    ("super_order_inflow_yuan", "超大单流入"),
    ("super_order_outflow_yuan", "超大单流出"),
    ("super_order_net_yuan", "超大单净额"),
    ("large_order_inflow_yuan", "大单流入"),
    ("large_order_outflow_yuan", "大单流出"),
    ("large_order_net_yuan", "大单净额"),
    ("medium_order_inflow_yuan", "中单流入"),
    ("medium_order_outflow_yuan", "中单流出"),
    ("medium_order_net_yuan", "中单净额"),
    ("small_order_inflow_yuan", "小单流入"),
    ("small_order_outflow_yuan", "小单流出"),
    ("small_order_net_yuan", "小单净额"),
)
_RATIO_FIELDS = (
    ("super_order_net_ratio", "超大单净占比"),
    ("large_order_net_ratio", "大单净占比"),
    ("medium_order_net_ratio", "中单净占比"),
    ("small_order_net_ratio", "小单净占比"),
)


def parse_sector_flow_file(path: Path) -> list[SectorFlowInput]:
    """Read and validate a complete sector-flow export before returning any record."""

    text = _read_text(path)
    lines = [
        (line_number, line)
        for line_number, line in enumerate(text.splitlines(), start=1)
        if line.strip()
    ]
    if not lines:
        raise ValidationError("line 1: missing header")

    _header_line_number, header = lines[0]
    columns = _header_positions(header)
    records: list[SectorFlowInput] = []
    sector_codes: set[str] = set()
    for line_number, line in lines[1:]:
        record = _parse_row(line, line_number=line_number, columns=columns)
        if record.sector_code in sector_codes:
            raise ValidationError(
                f"line {line_number}: duplicate sector code: {record.sector_code}"
            )
        sector_codes.add(record.sector_code)
        records.append(record)
    return records


def parse_money_to_yuan(value: str, *, line_number: int) -> Decimal:
    """Convert a signed Chinese ``亿`` or ``万`` amount into an exact yuan Decimal."""

    match = re.fullmatch(r"([+-]?\d+(?:\.\d+)?)(亿|万)", value.strip())
    if match is None:
        raise ValidationError(f"line {line_number}: unknown money unit: {value}")
    multiplier = Decimal("100000000") if match.group(2) == "亿" else Decimal("10000")
    return Decimal(match.group(1)) * multiplier


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8", "gb18030", "gbk"):
        try:
            return raw.decode(encoding, errors="strict")
        except UnicodeDecodeError:
            continue
    raise ValidationError(f"line 1: unable to decode sector-flow file: {path}")


def _header_positions(header: str) -> dict[str, int]:
    cells = _cells(header)
    positions = {cell: index for index, cell in enumerate(cells)}
    missing = [heading for heading in _REQUIRED_HEADINGS if heading not in positions]
    if missing:
        raise ValidationError(f"line 1: missing required column: {missing[0]}")
    return {heading: positions[heading] for heading in _REQUIRED_HEADINGS}


def _parse_row(line: str, *, line_number: int, columns: dict[str, int]) -> SectorFlowInput:
    cells = _cells(line)
    values = {
        heading: _required_cell(cells, index, heading=heading, line_number=line_number)
        for heading, index in columns.items()
    }
    money = {
        field: parse_money_to_yuan(values[heading], line_number=line_number)
        for field, heading in _MONEY_FIELDS
    }
    ratios = {
        field: _parse_decimal(values[heading], heading=heading, line_number=line_number)
        for field, heading in _RATIO_FIELDS
    }
    return SectorFlowInput(
        sector_code=values["代码"],
        sector_name=values["名称"],
        latest=_parse_decimal(values["最新"], heading="最新", line_number=line_number),
        change_percent=_parse_decimal(values["涨幅%"], heading="涨幅%", line_number=line_number),
        **money,
        **ratios,
    )


def _cells(line: str) -> list[str]:
    return re.split(r"\s+", line.strip())


def _required_cell(cells: list[str], index: int, *, heading: str, line_number: int) -> str:
    if index >= len(cells) or not cells[index]:
        raise ValidationError(f"line {line_number}: missing required cell: {heading}")
    return cells[index]


def _parse_decimal(value: str, *, heading: str, line_number: int) -> Decimal:
    try:
        decimal = Decimal(value)
    except InvalidOperation as exc:
        raise ValidationError(
            f"line {line_number}: invalid decimal for {heading}: {value}"
        ) from exc
    if not decimal.is_finite():
        raise ValidationError(f"line {line_number}: invalid decimal for {heading}: {value}")
    return decimal
