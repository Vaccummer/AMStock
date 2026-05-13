"""Fetch A-share fundamental and financial statement data from AKShare."""

from __future__ import annotations

import argparse
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
    sina_stock_code,
)
from amstock.baostock_io import baostock_session, normalize_baostock_code, result_set_payload

if TYPE_CHECKING:
    import pandas as pd


REPORT_TYPE_MAP = {
    "balance": "资产负债表",
    "income": "利润表",
    "cash-flow": "现金流量表",
}
BAOSTOCK_REPORT_MAP = {
    "abstract": "profit",
    "balance": "balance",
    "income": "profit",
    "cash-flow": "cash-flow",
}


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--kind",
        choices=["abstract", "report"],
        default="abstract",
        help="Fundamental dataset to fetch.",
    )
    parser.add_argument("--symbol", required=True, help="A-share code, e.g. 600519.")
    parser.add_argument("--year", type=int, help="Report year for BaoStock fallback.")
    parser.add_argument(
        "--quarter",
        type=int,
        choices=[1, 2, 3, 4],
        help="Report quarter for BaoStock fallback.",
    )
    parser.add_argument(
        "--report-type",
        choices=sorted(REPORT_TYPE_MAP),
        default="balance",
        help="Report type for --kind report.",
    )
    parser.add_argument("--limit", type=int, help="Maximum rows to include in JSON output.")
    add_network_options(parser)
    return parser


def fetch(args: argparse.Namespace) -> tuple[str, dict[str, object], pd.DataFrame]:
    """Fetch the requested fundamental dataset."""

    import akshare as ak

    if args.kind == "abstract":
        symbol = normalize_a_stock_code(args.symbol)
        return "stock_financial_abstract", {"symbol": symbol}, ak.stock_financial_abstract(symbol)

    stock = sina_stock_code(args.symbol)
    report_type = REPORT_TYPE_MAP[args.report_type]
    params = {"stock": stock, "symbol": report_type}
    return "stock_financial_report_sina", params, ak.stock_financial_report_sina(**params)


def fetch_fallback(args: argparse.Namespace, error: Exception) -> dict[str, object]:
    """Fetch a best-effort financial fallback through BaoStock."""

    if args.year is None or args.quarter is None:
        msg = "BaoStock financial fallback requires --year and --quarter"
        raise RuntimeError(msg)

    fallback_kind = (
        BAOSTOCK_REPORT_MAP["abstract"]
        if args.kind == "abstract"
        else BAOSTOCK_REPORT_MAP[args.report_type]
    )
    params = {
        "code": normalize_baostock_code(args.symbol),
        "year": args.year,
        "quarter": args.quarter,
    }
    with baostock_session() as bs:
        functions = {
            "profit": bs.query_profit_data,
            "balance": bs.query_balance_data,
            "cash-flow": bs.query_cash_flow_data,
        }
        result_set = functions[fallback_kind](**params)
        payload = result_set_payload(
            f"query_{fallback_kind.replace('-', '_')}_data",
            params,
            result_set,
            limit=args.limit,
        )
    function = (
        "stock_financial_abstract"
        if args.kind == "abstract"
        else "stock_financial_report_sina"
    )
    return add_fallback_metadata(payload, function=function, error=error)


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
