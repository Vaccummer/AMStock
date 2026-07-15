"""Tests for the sector-flow text parser."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from amstock.exceptions import ValidationError
from amstock.sector_flow_io import parse_sector_flow_file

if TYPE_CHECKING:
    from pathlib import Path


GBK_SAMPLE = "\n".join(
    (
        "序 代码 名称 最新 涨幅% 主力净流入 集合竞价 超大单流入 超大单流出 超大单净额 超大单净占比 "
        "大单流入 大单流出 大单净额 大单净占比 中单流入 中单流出 中单净额 中单净占比 "
        "小单流入 小单流出 小单净额 小单净占比",
        "1 BK1106 创新药 1234.56 1.23 76.6亿 120万 80亿 3.4亿 76.6亿 12.3 20亿 8亿 12亿 4.5 "
        "5亿 6亿 -1亿 -2.0 3亿 4亿 -1亿 -1.5",
        "2 BK0477 航运港口 987.65 -0.45 -2355万 -30万 1亿 3000万 7000万 3.2 1.2亿 4500万 "
        "7500万 2.1 8000万 1亿 -2000万 -0.8 6000万 7000万 -1000万 -0.4",
    )
)


def test_parse_sector_flow_file_decodes_gbk_and_converts_money_units(tmp_path: Path) -> None:
    path = tmp_path / "flow.txt"
    path.write_bytes(GBK_SAMPLE.encode("gbk"))

    records = parse_sector_flow_file(path)

    assert records[0].sector_code == "BK1106"
    assert records[0].sector_name == "创新药"
    assert records[0].latest == Decimal("1234.56")
    assert records[0].main_net_inflow_yuan == Decimal("7660000000")
    assert records[1].main_net_inflow_yuan == Decimal("-23550000")
    assert records[1].large_order_inflow_yuan == Decimal("120000000")


def test_parse_sector_flow_file_rejects_bad_amount_before_returning_records(tmp_path: Path) -> None:
    path = tmp_path / "flow.txt"
    path.write_text(GBK_SAMPLE.replace("76.6亿", "76.6千"), encoding="utf-8")

    with pytest.raises(ValidationError, match=r"line 2.*unknown money unit"):
        parse_sector_flow_file(path)


def test_parse_sector_flow_file_rejects_duplicate_sector_code(tmp_path: Path) -> None:
    path = tmp_path / "flow.txt"
    path.write_text(GBK_SAMPLE.replace("BK0477", "BK1106"), encoding="utf-8")

    with pytest.raises(ValidationError, match=r"line 3.*duplicate sector code.*BK1106"):
        parse_sector_flow_file(path)


def test_parse_sector_flow_file_rejects_invalid_required_decimal(tmp_path: Path) -> None:
    path = tmp_path / "flow.txt"
    path.write_text(GBK_SAMPLE.replace("1234.56", "not-a-number"), encoding="utf-8")

    with pytest.raises(ValidationError, match=r"line 2.*invalid decimal.*最新"):
        parse_sector_flow_file(path)


def test_parse_sector_flow_file_rejects_non_finite_decimal(tmp_path: Path) -> None:
    path = tmp_path / "flow.txt"
    path.write_text(GBK_SAMPLE.replace("1234.56", "NaN"), encoding="utf-8")

    with pytest.raises(ValidationError, match=r"line 2.*invalid decimal.*最新"):
        parse_sector_flow_file(path)
