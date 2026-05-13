"""Fetch A-share quote and market summary data from AKShare."""

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
)
from amstock.baostock_io import baostock_session, normalize_baostock_code, result_set_payload

if TYPE_CHECKING:
    import pandas as pd


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--kind",
        choices=["a-spot", "individual", "sse-summary", "szse-summary"],
        default="a-spot",
        help="Dataset to fetch.",
    )
    parser.add_argument("--symbol", help="A-share code for --kind individual, e.g. 600519.")
    parser.add_argument(
        "--date",
        help=(
            "Trading date for szse-summary in YYYYMMDD format. "
            "AKShare default is used if omitted."
        ),
    )
    parser.add_argument("--limit", type=int, help="Maximum rows to include in JSON output.")
    add_network_options(parser)
    return parser


def fetch(args: argparse.Namespace) -> tuple[str, dict[str, object], pd.DataFrame]:
    """Fetch the requested dataset."""

    import akshare as ak

    if args.kind == "a-spot":
        return "stock_zh_a_spot_em", {}, ak.stock_zh_a_spot_em()

    if args.kind == "individual":
        if not args.symbol:
            msg = "--symbol is required for --kind individual"
            raise ValueError(msg)
        symbol = normalize_a_stock_code(args.symbol)
        return "stock_individual_info_em", {"symbol": symbol}, ak.stock_individual_info_em(symbol)

    if args.kind == "sse-summary":
        return "stock_sse_summary", {}, ak.stock_sse_summary()

    params = {}
    if args.date:
        params["date"] = args.date
    return "stock_szse_summary", params, ak.stock_szse_summary(**params)


def fetch_fallback(args: argparse.Namespace, error: Exception) -> dict[str, object]:
    """Fetch a best-effort quote fallback through BaoStock."""

    if args.kind == "a-spot":
        params = {"day": _baostock_day(args.date)}
        with baostock_session() as bs:
            result_set = bs.query_all_stock(**params)
            payload = result_set_payload("query_all_stock", params, result_set, limit=args.limit)
        return add_fallback_metadata(payload, function="stock_zh_a_spot_em", error=error)

    if args.kind == "individual" and args.symbol:
        params = {"code": normalize_baostock_code(args.symbol)}
        with baostock_session() as bs:
            result_set = bs.query_stock_basic(**params)
            payload = result_set_payload("query_stock_basic", params, result_set, limit=args.limit)
        return add_fallback_metadata(payload, function="stock_individual_info_em", error=error)

    msg = f"BaoStock fallback is not available for market quote kind {args.kind!r}"
    raise RuntimeError(msg)


def _baostock_day(value: str | None) -> str | None:
    """Convert YYYYMMDD to YYYY-MM-DD for BaoStock query_all_stock."""

    if not value:
        return None
    if "-" in value:
        return value
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}"


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
