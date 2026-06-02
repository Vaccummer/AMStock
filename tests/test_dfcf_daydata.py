from __future__ import annotations

import struct
from typing import TYPE_CHECKING

import pytest

from amstock.dfcf_daydata import (
    DAY_RECORD_STRUCT,
    HEADER_SIZE,
    INDEX_ENTRY_SIZE,
    DayDataReader,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_daydata_reader_parses_symbol_bars(tmp_path: Path) -> None:
    path = tmp_path / "DayData_SH_V43.dat"
    max_records = 3
    index_capacity = 200
    data_offset = HEADER_SIZE + max_records * index_capacity

    header = struct.pack(
        "<12I",
        1,
        3,
        1,
        1,
        max_records,
        index_capacity,
        0,
        0,
        0,
        0,
        0,
        0,
    )
    index = _index_entry("600519", record_count=2, ordinal=0)
    padding = b"\xff" * (data_offset - len(header) - len(index))
    records = b"".join(
        [
            DAY_RECORD_STRUCT.pack(
                20260601,
                0,
                1327.0,
                1309.6,
                1327.0,
                1301.31,
                4384460,
                0,
                5741133312.0,
            ),
            DAY_RECORD_STRUCT.pack(20260602, 0, 1330.0, 1328.0, 1338.0, 1320.0, 100, 0, 200.0),
            b"\0" * 40,
        ]
    )
    path.write_bytes(header + index + padding + records)

    reader = DayDataReader(path)
    assert reader.list_symbols()[0].code == "600519"

    bars = reader.read_symbol("600519")
    assert len(bars) == 2
    assert bars[0].date_iso == "2026-06-01"
    assert bars[0].open == pytest.approx(1309.6)
    assert bars[0].high == 1327.0
    assert bars[0].low == pytest.approx(1301.31)
    assert bars[0].close == 1327.0
    assert bars[0].volume == 4384460
    assert bars[0].amount == 5741133312.0


def _index_entry(code: str, record_count: int, ordinal: int) -> bytes:
    code_bytes = code.encode("ascii") + b"\0" * (24 - len(code))
    return (
        code_bytes
        + struct.pack("<II", record_count, ordinal)
        + b"\xff" * (INDEX_ENTRY_SIZE - 32)
    )
