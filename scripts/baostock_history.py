"""Fetch historical K-line data from BaoStock."""

from __future__ import annotations

import argparse

from amstock.baostock_io import (
    baostock_session,
    emit_json,
    error_payload,
    normalize_baostock_code,
    result_set_payload,
)

DEFAULT_FIELDS = "date,code,open,high,low,close,volume,amount,turn,pctChg"


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", required=True, help="Stock code, e.g. 600000 or sh.600000.")
    parser.add_argument("--start-date", required=True, help="Start date in YYYY-MM-DD format.")
    parser.add_argument("--end-date", required=True, help="End date in YYYY-MM-DD format.")
    parser.add_argument(
        "--frequency",
        choices=["d", "w", "m", "5", "15", "30", "60"],
        default="d",
        help="K-line frequency.",
    )
    parser.add_argument(
        "--adjustflag",
        choices=["1", "2", "3"],
        default="2",
        help="1: backward adjusted, 2: forward adjusted, 3: unadjusted.",
    )
    parser.add_argument("--fields", default=DEFAULT_FIELDS, help="BaoStock field list.")
    parser.add_argument("--limit", type=int, help="Maximum rows to include in JSON output.")
    return parser


def main() -> None:
    """Run the script."""

    args = build_parser().parse_args()
    try:
        params = {
            "code": normalize_baostock_code(args.symbol),
            "fields": args.fields,
            "start_date": args.start_date,
            "end_date": args.end_date,
            "frequency": args.frequency,
            "adjustflag": args.adjustflag,
        }
        with baostock_session() as bs:
            result_set = bs.query_history_k_data_plus(**params)
            emit_json(
                result_set_payload(
                    "query_history_k_data_plus",
                    params,
                    result_set,
                    limit=args.limit,
                )
            )
    except Exception as exc:
        emit_json(error_payload(exc))
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
