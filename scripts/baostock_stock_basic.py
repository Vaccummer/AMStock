"""Fetch stock basic information from BaoStock."""

from __future__ import annotations

import argparse

from amstock.baostock_io import (
    baostock_session,
    emit_json,
    error_payload,
    normalize_baostock_code,
    result_set_payload,
)


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", help="Stock code, e.g. 600000 or sh.600000.")
    parser.add_argument("--name", help="Stock name query supported by BaoStock.")
    parser.add_argument("--limit", type=int, help="Maximum rows to include in JSON output.")
    return parser


def main() -> None:
    """Run the script."""

    args = build_parser().parse_args()
    try:
        params: dict[str, object] = {}
        if args.symbol:
            params["code"] = normalize_baostock_code(args.symbol)
        if args.name:
            params["code_name"] = args.name
        if not params:
            msg = "provide --symbol or --name"
            raise ValueError(msg)

        with baostock_session() as bs:
            result_set = bs.query_stock_basic(**params)
            emit_json(result_set_payload("query_stock_basic", params, result_set, limit=args.limit))
    except Exception as exc:
        emit_json(error_payload(exc))
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
