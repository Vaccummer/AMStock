"""Fetch A-share concept and industry board data from AKShare."""

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
)
from amstock.baostock_io import baostock_session, result_set_payload

if TYPE_CHECKING:
    import pandas as pd


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--kind",
        choices=["concept-list", "concept-cons", "industry-list", "industry-cons"],
        default="concept-list",
        help="Board dataset to fetch.",
    )
    parser.add_argument(
        "--symbol",
        help="Board name for constituent queries, e.g. 机器人概念 or 小金属.",
    )
    parser.add_argument("--limit", type=int, help="Maximum rows to include in JSON output.")
    add_network_options(parser)
    return parser


def fetch(args: argparse.Namespace) -> tuple[str, dict[str, object], pd.DataFrame]:
    """Fetch the requested board dataset."""

    import akshare as ak

    if args.kind == "concept-list":
        return "stock_board_concept_name_em", {}, ak.stock_board_concept_name_em()

    if args.kind == "industry-list":
        return "stock_board_industry_name_em", {}, ak.stock_board_industry_name_em()

    if not args.symbol:
        msg = "--symbol is required for constituent queries"
        raise ValueError(msg)

    if args.kind == "concept-cons":
        params = {"symbol": args.symbol}
        return "stock_board_concept_cons_em", params, ak.stock_board_concept_cons_em(**params)

    params = {"symbol": args.symbol}
    return "stock_board_industry_cons_em", params, ak.stock_board_industry_cons_em(**params)


def fetch_fallback(args: argparse.Namespace, error: Exception) -> dict[str, object]:
    """Fetch a best-effort sector fallback through BaoStock."""

    if args.kind != "industry-list":
        msg = f"BaoStock fallback is not available for sector kind {args.kind!r}"
        raise RuntimeError(msg)

    params = {"code": "", "date": ""}
    with baostock_session() as bs:
        result_set = bs.query_stock_industry(**params)
        payload = result_set_payload("query_stock_industry", params, result_set, limit=args.limit)
    return add_fallback_metadata(payload, function="stock_board_industry_name_em", error=error)


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
