"""Agent-facing source data CLI for AMStock."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal

import typer

from amstock.akshare_io import emit_json, error_payload
from amstock.biying_io import DEFAULT_TIMEOUT_SECONDS, fetch_biying_dataset
from amstock.src_queries import (
    capabilities_payload,
    fetch_a_spot,
    fetch_exchange_summary,
    fetch_financial_abstract,
    fetch_financial_report,
    fetch_industry_list,
    fetch_price_history,
    fetch_stock_basic,
)

if TYPE_CHECKING:
    from collections.abc import Callable

app = typer.Typer(no_args_is_help=True)

LimitOption = Annotated[int | None, typer.Option("--limit", help="Maximum rows to return.")]
NoProxyOption = Annotated[
    bool,
    typer.Option("--no-proxy", help="Disable proxy environment variables for this run."),
]
Ipv4Option = Annotated[bool, typer.Option("--ipv4", help="Force IPv4 DNS resolution.")]


@app.command("capabilities")
def capabilities() -> None:
    """Print supported commands and output contract as JSON."""

    emit_json(capabilities_payload())


@app.command("a-spot")
def a_spot(
    date: Annotated[
        str | None,
        typer.Option("--date", help="Trading date in YYYYMMDD format for BaoStock."),
    ] = None,
    limit: LimitOption = None,
    no_proxy: NoProxyOption = False,
    ipv4: Ipv4Option = False,
) -> None:
    """Fetch all A-share spot/basic trading list data from BaoStock."""

    _run_json(
        lambda: fetch_a_spot(date=date, limit=limit, no_proxy=no_proxy, ipv4=ipv4),
    )


@app.command("stock-basic")
def stock_basic(
    symbol: Annotated[str, typer.Option("--symbol", help="A-share code, e.g. 600519.")],
    limit: LimitOption = None,
    no_proxy: NoProxyOption = False,
    ipv4: Ipv4Option = False,
) -> None:
    """Fetch one A-share's BaoStock company/listing information."""

    _run_json(
        lambda: fetch_stock_basic(symbol=symbol, limit=limit, no_proxy=no_proxy, ipv4=ipv4),
    )


@app.command("price-history")
def price_history(
    symbol: Annotated[str, typer.Option("--symbol", help="A-share code, e.g. 600519.")],
    period: Annotated[
        Literal["daily", "weekly", "monthly"],
        typer.Option("--period", help="K-line period."),
    ] = "daily",
    start_date: Annotated[
        str,
        typer.Option("--start-date", help="Start date in YYYYMMDD format."),
    ] = "19700101",
    end_date: Annotated[str, typer.Option("--end-date", help="End date in YYYYMMDD format.")] = (
        "20500101"
    ),
    adjust: Annotated[
        Literal["none", "qfq", "hfq"],
        typer.Option("--adjust", help="Price adjustment mode."),
    ] = "none",
    limit: LimitOption = None,
    no_proxy: NoProxyOption = False,
    ipv4: Ipv4Option = False,
) -> None:
    """Fetch BaoStock A-share historical K-line data."""

    _run_json(
        lambda: fetch_price_history(
            symbol=symbol,
            period=period,
            start_date=start_date,
            end_date=end_date,
            adjust=adjust,
            limit=limit,
            no_proxy=no_proxy,
            ipv4=ipv4,
        ),
    )


@app.command("exchange-summary")
def exchange_summary(
    exchange: Annotated[
        Literal["sse", "szse"],
        typer.Option("--exchange", help="Exchange to query: sse or szse."),
    ],
    date: Annotated[
        str | None,
        typer.Option("--date", help="SZSE trading date in YYYYMMDD format."),
    ] = None,
    limit: LimitOption = None,
    no_proxy: NoProxyOption = False,
    ipv4: Ipv4Option = False,
) -> None:
    """Fetch Shanghai or Shenzhen exchange summary data."""

    _run_json(
        lambda: fetch_exchange_summary(
            exchange=exchange,
            date=date,
            limit=limit,
            no_proxy=no_proxy,
            ipv4=ipv4,
        ),
    )


@app.command("financial-abstract")
def financial_abstract(
    symbol: Annotated[str, typer.Option("--symbol", help="A-share code, e.g. 600519.")],
    limit: LimitOption = None,
    no_proxy: NoProxyOption = False,
    ipv4: Ipv4Option = False,
) -> None:
    """Fetch financial abstract data."""

    _run_json(
        lambda: fetch_financial_abstract(
            symbol=symbol,
            limit=limit,
            no_proxy=no_proxy,
            ipv4=ipv4,
        ),
    )


@app.command("financial-report")
def financial_report(
    symbol: Annotated[str, typer.Option("--symbol", help="A-share code, e.g. 600519.")],
    report_type: Annotated[
        Literal["balance", "income", "cash-flow"],
        typer.Option("--report-type", help="Report type to query."),
    ],
    limit: LimitOption = None,
    no_proxy: NoProxyOption = False,
    ipv4: Ipv4Option = False,
) -> None:
    """Fetch a financial statement."""

    _run_json(
        lambda: fetch_financial_report(
            symbol=symbol,
            report_type=report_type,
            limit=limit,
            no_proxy=no_proxy,
            ipv4=ipv4,
        ),
    )


@app.command("industry-list")
def industry_list(
    limit: LimitOption = None,
    no_proxy: NoProxyOption = False,
    ipv4: Ipv4Option = False,
) -> None:
    """Fetch BaoStock industry classification data."""

    _run_json(
        lambda: fetch_industry_list(limit=limit, no_proxy=no_proxy, ipv4=ipv4),
    )


@app.command("biying")
def biying(
    dataset: Annotated[str, typer.Option("--dataset", help="Biying dataset name.")],
    symbol: Annotated[
        str | None,
        typer.Option("--symbol", help="Six-digit stock code for stock-scoped datasets."),
    ] = None,
    market_symbol: Annotated[
        str | None,
        typer.Option("--market-symbol", help="Market symbol such as 000001.SZ."),
    ] = None,
    index: Annotated[
        str | None,
        typer.Option("--index", help="Index symbol with suffix, e.g. 000001.SH."),
    ] = None,
    fund: Annotated[str | None, typer.Option("--fund", help="Fund code.")] = None,
    sector: Annotated[str | None, typer.Option("--sector", help="Sector name.")] = None,
    code: Annotated[
        str | None,
        typer.Option("--code", help="Biying index, industry, or concept code."),
    ] = None,
    date: Annotated[
        str | None,
        typer.Option("--date", help="Trading date, usually YYYY-MM-DD for stock pools."),
    ] = None,
    period: Annotated[
        str,
        typer.Option("--period", help="Bar period such as d, w, m, 1m, 5m, 15m, 30m, 60m."),
    ] = "d",
    adjust: Annotated[
        str,
        typer.Option("--adjust", help="Adjustment type used by Biying, commonly n/q/h."),
    ] = "n",
    st: Annotated[str | None, typer.Option("--st", help="Start date/time query parameter.")] = None,
    et: Annotated[str | None, typer.Option("--et", help="End date/time query parameter.")] = None,
    lt: Annotated[
        int | None,
        typer.Option("--lt", help="Latest row count query parameter."),
    ] = None,
    stock_codes: Annotated[
        str | None,
        typer.Option("--stock-codes", help="Comma-separated stock codes for multi-quote datasets."),
    ] = None,
    licences: Annotated[
        str | None,
        typer.Option(
            "--licences",
            help="Biying licences separated by comma, semicolon, or whitespace.",
        ),
    ] = None,
    base_url: Annotated[
        str,
        typer.Option("--base-url", help="Biying API base URL."),
    ] = "https://api.biyingapi.com",
    timeout: Annotated[
        float,
        typer.Option("--timeout", help="HTTP timeout in seconds."),
    ] = DEFAULT_TIMEOUT_SECONDS,
    limit: LimitOption = None,
) -> None:
    """Fetch a Biying dataset."""

    params: dict[str, str | int | None] = {
        "symbol": symbol,
        "market_symbol": market_symbol or symbol,
        "index": index,
        "fund": fund,
        "sector": sector,
        "code": code,
        "date": date,
        "period": period,
        "adjust": adjust,
        "st": st,
        "et": et,
        "lt": lt,
        "stock_codes": stock_codes,
    }
    _run_json(
        lambda: fetch_biying_dataset(
            dataset=dataset,
            params=params,
            licences_value=licences,
            base_url=base_url,
            timeout=timeout,
            limit=limit,
        ),
    )


def _run_json(operation: Callable[[], dict[str, object]]) -> None:
    """Run a query operation and emit a single JSON object."""

    try:
        payload = operation()
        emit_json(payload)
    except Exception as exc:
        emit_json(error_payload(exc))
        raise typer.Exit(1) from exc


def main() -> None:
    """Run the source data CLI."""

    app()


if __name__ == "__main__":
    main()
