"""Probe BaoStock login connectivity."""

from __future__ import annotations

import argparse

from amstock.baostock_io import emit_json, error_payload, suppress_stdout


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""

    return argparse.ArgumentParser(description=__doc__)


def main() -> None:
    """Run the login probe."""

    build_parser().parse_args()
    try:
        import baostock as bs

        with suppress_stdout():
            login_result = bs.login()
        try:
            emit_json(
                {
                    "ok": login_result.error_code == "0",
                    "source": "baostock",
                    "function": "login",
                    "error_code": login_result.error_code,
                    "error_msg": login_result.error_msg,
                }
            )
        finally:
            with suppress_stdout():
                bs.logout()
    except Exception as exc:
        emit_json(error_payload(exc))
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
