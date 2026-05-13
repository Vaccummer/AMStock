"""Fetch A-share historical K-line data from AKShare."""

from __future__ import annotations

import argparse
from datetime import datetime
from typing import TYPE_CHECKING

from amstock.akshare_io import (
    add_fallback_metadata,
    add_network_options,
    configure_network,
    dataframe_payload,
    emit_json,
    error_payload,
    is_connection_error,
    normalize_a_stock_code,
)
from amstock.baostock_io import baostock_session, normalize_baostock_code, result_set_payload

if TYPE_CHECKING:
    import pandas as pd


ADJUST_MAP = {
    "none": "",
    "qfq": "qfq",
    "hfq": "hfq",
}
BAOSTOCK_ADJUST_MAP = {
    "none": "3",
    "qfq": "2",
    "hfq": "1",
}
BAOSTOCK_PERIOD_MAP = {
    "daily": "d",
    "weekly": "w",
    "monthly": "m",
}
BAOSTOCK_FIELDS = "date,code,open,high,low,close,volume,amount,turn,pctChg"


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", required=True, help="A-share code, e.g. 600519.")
    parser.add_argument(
        "--period",
        choices=["daily", "weekly", "monthly"],
        default="daily",
        help="K-line period.",
    )
    parser.add_argument("--start-date", default="19700101", help="Start date in YYYYMMDD format.")
    parser.add_argument("--end-date", default="20500101", help="End date in YYYYMMDD format.")
    parser.add_argument(
        "--adjust",
        choices=sorted(ADJUST_MAP),
        default="none",
        help="Price adjustment mode.",
    )
    parser.add_argument("--limit", type=int, help="Maximum rows to include in JSON output.")
    add_network_options(parser)
    return parser


def fetch(args: argparse.Namespace) -> tuple[str, dict[str, object], pd.DataFrame]:
    """Fetch historical prices."""

    import akshare as ak

    params = {
        "symbol": normalize_a_stock_code(args.symbol),
        "period": args.period,
        "start_date": args.start_date,
        "end_date": args.end_date,
        "adjust": ADJUST_MAP[args.adjust],
    }
    return "stock_zh_a_hist", params, ak.stock_zh_a_hist(**params)


def fetch_fallback(args: argparse.Namespace, error: Exception) -> dict[str, object]:
    """Fetch historical prices through BaoStock."""

    params = {
        "code": normalize_baostock_code(args.symbol),
        "fields": BAOSTOCK_FIELDS,
        "start_date": _baostock_date(args.start_date),
        "end_date": _baostock_date(args.end_date),
        "frequency": BAOSTOCK_PERIOD_MAP[args.period],
        "adjustflag": BAOSTOCK_ADJUST_MAP[args.adjust],
    }
    with baostock_session() as bs:
        result_set = bs.query_history_k_data_plus(**params)
        payload = result_set_payload(
            "query_history_k_data_plus",
            params,
            result_set,
            limit=args.limit,
        )
    return add_fallback_metadata(payload, function="stock_zh_a_hist", error=error)


def _baostock_date(value: str) -> str:
    """Convert YYYYMMDD to YYYY-MM-DD for BaoStock."""

    if "-" in value:
        return value
    return datetime.strptime(value, "%Y%m%d").strftime("%Y-%m-%d")


def main() -> None:
    """Run the script."""

    args = build_parser().parse_args()
    try:
        configure_network(no_proxy=args.no_proxy, ipv4=args.ipv4)
        function, params, dataframe = fetch(args)
        emit_json(dataframe_payload(function, params, dataframe, limit=args.limit))
    except Exception as exc:
        if is_connection_error(exc):
            try:
                emit_json(fetch_fallback(args, exc))
                return
            except Exception as fallback_exc:
                emit_json(error_payload(fallback_exc))
                raise SystemExit(1) from fallback_exc
        emit_json(error_payload(exc))
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
