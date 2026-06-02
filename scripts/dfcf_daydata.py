"""Inspect Eastmoney desktop V43 daily K-line files."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from amstock.dfcf_daydata import DayDataReader  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", help="Path to DayData_*_V43.dat.")
    parser.add_argument("--symbol", help="Stock/index code to parse, for example 600519.")
    parser.add_argument("--list", action="store_true", help="List symbols from the index section.")
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum rows to print; use 0 for all.",
    )
    parser.add_argument(
        "--tail",
        action="store_true",
        help="Print latest rows instead of earliest rows.",
    )
    parser.add_argument("--format", choices=["json", "csv"], default="json", help="Output format.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    reader = DayDataReader(args.file)
    if args.list:
        entries = reader.list_symbols()
        rows = [
            {"code": entry.code, "record_count": entry.record_count, "ordinal": entry.ordinal}
            for entry in _limit(entries, args.limit, args.tail)
        ]
        _emit(rows, args.format)
        return

    if not args.symbol:
        raise SystemExit("use --symbol CODE to parse bars, or --list to inspect index entries")

    bars = reader.read_symbol(args.symbol)
    _emit([bar.as_dict() for bar in _limit(bars, args.limit, args.tail)], args.format)


def _limit[T](rows: list[T], limit: int, tail: bool) -> list[T]:
    if limit == 0:
        return rows
    return rows[-limit:] if tail else rows[:limit]


def _emit(rows: list[dict[str, int | float | str]], output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    writer = csv.DictWriter(sys.stdout, fieldnames=list(rows[0]) if rows else [])
    writer.writeheader()
    writer.writerows(rows)


if __name__ == "__main__":
    main()
