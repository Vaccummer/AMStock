"""Parse Eastmoney desktop DayData_SH/SZ_V43 daily K-line files."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

HEADER_SIZE = 48
HEADER_STRUCT = struct.Struct("<12I")
INDEX_ENTRY_SIZE = 516
DAY_RECORD_SIZE = 40
DAY_RECORD_STRUCT = struct.Struct("<IIffffIId")


@dataclass(frozen=True, slots=True)
class DayDataHeader:
    """Header values from a V43 daily data file."""

    raw: tuple[int, ...]

    @property
    def stock_count(self) -> int:
        return self.raw[2]

    @property
    def active_count(self) -> int:
        return self.raw[3]

    @property
    def max_records(self) -> int:
        return self.raw[4]

    @property
    def index_capacity(self) -> int:
        return self.raw[5]

    @property
    def data_offset(self) -> int:
        return HEADER_SIZE + self.max_records * self.index_capacity


@dataclass(frozen=True, slots=True)
class DayDataIndexEntry:
    """One symbol entry from the fixed-width index section."""

    code: str
    record_count: int
    ordinal: int


@dataclass(frozen=True, slots=True)
class DayBar:
    """One daily K-line bar."""

    date: int
    open: float
    high: float
    low: float
    close: float
    volume: int
    amount: float

    @property
    def date_iso(self) -> str:
        text = str(self.date)
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"

    def as_dict(self) -> dict[str, int | float | str]:
        return {
            "date": self.date_iso,
            "open": round(self.open, 6),
            "high": round(self.high, 6),
            "low": round(self.low, 6),
            "close": round(self.close, 6),
            "volume": self.volume,
            "amount": round(self.amount, 6),
        }


class DayDataReader:
    """Reader for Eastmoney desktop V43 daily data files."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.header = self._read_header()

    def list_symbols(self) -> list[DayDataIndexEntry]:
        with self.path.open("rb") as handle:
            handle.seek(HEADER_SIZE)
            return [self._read_index_entry(handle) for _ in range(self.header.stock_count)]

    def read_symbol(self, code: str) -> list[DayBar]:
        entry = self.find_symbol(code)
        block_index = self._data_block_base() + entry.ordinal
        offset = self.header.data_offset + block_index * self._block_size()
        bars: list[DayBar] = []
        with self.path.open("rb") as handle:
            handle.seek(offset)
            for _ in range(entry.record_count):
                chunk = handle.read(DAY_RECORD_SIZE)
                if len(chunk) != DAY_RECORD_SIZE:
                    break
                bars.append(_unpack_day_bar(chunk))
        return bars

    def find_symbol(self, code: str) -> DayDataIndexEntry:
        for entry in self.list_symbols():
            if entry.code == code:
                return entry
        raise KeyError(f"symbol not found in {self.path}: {code}")

    def _read_header(self) -> DayDataHeader:
        with self.path.open("rb") as handle:
            chunk = handle.read(HEADER_SIZE)
        if len(chunk) != HEADER_SIZE:
            raise ValueError(f"file is too small for a V43 header: {self.path}")
        return DayDataHeader(raw=HEADER_STRUCT.unpack(chunk))

    def _data_block_base(self) -> int:
        remaining = self.path.stat().st_size - self.header.data_offset
        if remaining < 0:
            raise ValueError(f"file is smaller than declared data offset: {self.path}")
        total_blocks = remaining // self._block_size()
        block_base = total_blocks - self.header.stock_count
        if block_base < 0:
            raise ValueError(f"file does not contain enough data blocks: {self.path}")
        return block_base

    def _block_size(self) -> int:
        return self.header.max_records * DAY_RECORD_SIZE

    @staticmethod
    def _read_index_entry(handle: BinaryIO) -> DayDataIndexEntry:
        chunk = handle.read(INDEX_ENTRY_SIZE)
        if len(chunk) != INDEX_ENTRY_SIZE:
            raise ValueError("unexpected end of file while reading index entry")
        code = chunk[:24].split(b"\0", 1)[0].decode("ascii")
        record_count, ordinal = struct.unpack("<II", chunk[24:32])
        return DayDataIndexEntry(code=code, record_count=record_count, ordinal=ordinal)


def _unpack_day_bar(chunk: bytes) -> DayBar:
    date, _reserved, close, open_, high, low, volume, _reserved2, amount = DAY_RECORD_STRUCT.unpack(
        chunk
    )
    return DayBar(
        date=date,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        amount=amount,
    )
