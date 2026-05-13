"""Fetch financial indicator data from BaoStock."""

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
    parser.add_argument(
        "--kind",
        choices=["profit", "operation", "growth", "balance", "cash-flow", "dupont"],
        default="profit",
        help="Financial dataset.",
    )
    parser.add_argument("--symbol", required=True, help="Stock code, e.g. 600000 or sh.600000.")
    parser.add_argument("--year", required=True, type=int, help="Report year.")
    parser.add_argument("--quarter", required=True, type=int, choices=[1, 2, 3, 4], help="Quarter.")
    parser.add_argument("--limit", type=int, help="Maximum rows to include in JSON output.")
    return parser


def main() -> None:
    """Run the script."""

    args = build_parser().parse_args()
    try:
        params = {
            "code": normalize_baostock_code(args.symbol),
            "year": args.year,
            "quarter": args.quarter,
        }
        with baostock_session() as bs:
            functions = {
                "profit": bs.query_profit_data,
                "operation": bs.query_operation_data,
                "growth": bs.query_growth_data,
                "balance": bs.query_balance_data,
                "cash-flow": bs.query_cash_flow_data,
                "dupont": bs.query_dupont_data,
            }
            function_name = f"query_{args.kind.replace('-', '_')}_data"
            result_set = functions[args.kind](**params)
            emit_json(result_set_payload(function_name, params, result_set, limit=args.limit))
    except Exception as exc:
        emit_json(error_payload(exc))
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
