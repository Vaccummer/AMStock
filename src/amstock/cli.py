"""Command-line entry point."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Annotated, Literal

import typer

from amstock import __version__
from amstock.biying_io import DEFAULT_TIMEOUT_SECONDS, fetch_biying_dataset
from amstock.exceptions import AMStockError
from amstock.services import create_application_context
from amstock.src_cli import app as sources_app
from amstock.src_queries import (
    fetch_a_spot,
    fetch_exchange_summary,
    fetch_financial_abstract,
    fetch_financial_report,
    fetch_industry_list,
    fetch_price_history,
    fetch_stock_basic,
)
from amstock.store_cli import app as portfolio_app

if TYPE_CHECKING:
    from collections.abc import Callable

app = typer.Typer(invoke_without_command=True, no_args_is_help=True)
db_app = typer.Typer(no_args_is_help=True)
stock_app = typer.Typer(no_args_is_help=True)
quote_app = typer.Typer(no_args_is_help=True)
sector_app = typer.Typer(no_args_is_help=True)
index_app = typer.Typer(no_args_is_help=True)
fund_app = typer.Typer(no_args_is_help=True)

LimitOption = Annotated[int | None, typer.Option("--limit", help="Maximum rows to return.")]
NoProxyOption = Annotated[
    bool,
    typer.Option("--no-proxy", help="Disable proxy environment variables for this run."),
]
Ipv4Option = Annotated[bool, typer.Option("--ipv4", help="Force IPv4 DNS resolution.")]
BiyingLicencesOption = Annotated[
    str | None,
    typer.Option(
        "--licences",
        help="Biying licences separated by comma, semicolon, or whitespace.",
    ),
]
BiyingTimeoutOption = Annotated[
    float,
    typer.Option("--timeout", help="Biying HTTP timeout in seconds."),
]
BiyingBaseUrlOption = Annotated[str, typer.Option("--base-url", help="Biying API base URL.")]

@app.callback()
def root(
    version: bool = typer.Option(False, "--version", help="Show the application version."),
) -> None:
    """AMStock command-line interface."""

    if version:
        typer.echo(__version__)
        raise typer.Exit


@app.command("init-db")
@db_app.command("init")
def init_db() -> None:
    """Create database tables for the current configuration."""

    try:
        context = create_application_context()
        context.database.create_schema()
        _echo_json({"ok": True, "database_url": context.settings.database_url})
    except AMStockError as exc:
        _exit_with_error(exc)


@stock_app.command("list")
def stock_list(
    date: Annotated[
        str | None,
        typer.Option("--date", help="Trading date in YYYYMMDD format for BaoStock."),
    ] = None,
    limit: LimitOption = None,
    no_proxy: NoProxyOption = False,
    ipv4: Ipv4Option = False,
) -> None:
    """Fetch all A-share stock list data."""

    _run_json(lambda: fetch_a_spot(date=date, limit=limit, no_proxy=no_proxy, ipv4=ipv4))


@stock_app.command("basic")
def stock_basic(
    symbol: Annotated[str, typer.Option("--symbol", help="A-share code, e.g. 600519.")],
    limit: LimitOption = None,
    no_proxy: NoProxyOption = False,
    ipv4: Ipv4Option = False,
) -> None:
    """Fetch one A-share's basic company/listing information."""

    _run_json(
        lambda: fetch_stock_basic(symbol=symbol, limit=limit, no_proxy=no_proxy, ipv4=ipv4),
    )


@stock_app.command("history")
def stock_history(
    symbol: Annotated[str, typer.Option("--symbol", help="A-share code, e.g. 600519.")],
    period: Annotated[
        Literal["daily", "weekly", "monthly"],
        typer.Option("--period", help="K-line period for BaoStock."),
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
    source: Annotated[
        Literal["baostock", "biying"],
        typer.Option("--source", help="Data source."),
    ] = "baostock",
    st: Annotated[
        str | None,
        typer.Option("--st", help="Biying start date/time query parameter."),
    ] = None,
    et: Annotated[
        str | None,
        typer.Option("--et", help="Biying end date/time query parameter."),
    ] = None,
    lt: Annotated[
        int | None,
        typer.Option("--lt", help="Biying latest row count query parameter."),
    ] = None,
    licences: BiyingLicencesOption = None,
    base_url: BiyingBaseUrlOption = "https://api.biyingapi.com",
    timeout: BiyingTimeoutOption = DEFAULT_TIMEOUT_SECONDS,
    limit: LimitOption = None,
    no_proxy: NoProxyOption = False,
    ipv4: Ipv4Option = False,
) -> None:
    """Fetch historical stock bars."""

    if source == "biying":
        _run_json(
            lambda: _fetch_biying(
                "stock-history",
                {
                    "symbol": symbol,
                    "market_symbol": symbol,
                    "period": _biying_period(period),
                    "adjust": _biying_adjust(adjust),
                    "st": st or start_date,
                    "et": et or end_date,
                    "lt": lt,
                },
                licences=licences,
                base_url=base_url,
                timeout=timeout,
                limit=limit,
            ),
        )
        return

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


@stock_app.command("financial")
def stock_financial(
    symbol: Annotated[str, typer.Option("--symbol", help="A-share code, e.g. 600519.")],
    report_type: Annotated[
        Literal["abstract", "balance", "income", "cash-flow", "pershareindex"],
        typer.Option("--report-type", help="Financial dataset."),
    ] = "abstract",
    source: Annotated[
        Literal["akshare", "biying"],
        typer.Option("--source", help="Data source."),
    ] = "akshare",
    st: Annotated[
        str | None,
        typer.Option("--st", help="Biying start date/time query parameter."),
    ] = None,
    et: Annotated[
        str | None,
        typer.Option("--et", help="Biying end date/time query parameter."),
    ] = None,
    licences: BiyingLicencesOption = None,
    base_url: BiyingBaseUrlOption = "https://api.biyingapi.com",
    timeout: BiyingTimeoutOption = DEFAULT_TIMEOUT_SECONDS,
    limit: LimitOption = None,
    no_proxy: NoProxyOption = False,
    ipv4: Ipv4Option = False,
) -> None:
    """Fetch financial abstracts, statements, or key indicators."""

    if source == "biying":
        dataset = {
            "abstract": "financial-indicator-summary",
            "balance": "financial-balance",
            "income": "financial-income",
            "cash-flow": "financial-cashflow",
            "pershareindex": "financial-pershareindex",
        }[report_type]
        _run_json(
            lambda: _fetch_biying(
                dataset,
                {"symbol": symbol, "market_symbol": symbol, "st": st, "et": et},
                licences=licences,
                base_url=base_url,
                timeout=timeout,
                limit=limit,
            ),
        )
        return

    if report_type == "abstract":
        _run_json(
            lambda: fetch_financial_abstract(
                symbol=symbol,
                limit=limit,
                no_proxy=no_proxy,
                ipv4=ipv4,
            ),
        )
        return

    if report_type == "pershareindex":
        msg = "pershareindex requires --source biying"
        _run_json(lambda: (_raise_value_error(msg)))
        return

    _run_json(
        lambda: fetch_financial_report(
            symbol=symbol,
            report_type=report_type,
            limit=limit,
            no_proxy=no_proxy,
            ipv4=ipv4,
        ),
    )


@stock_app.command("holders")
def stock_holders(
    symbol: Annotated[str, typer.Option("--symbol", help="A-share code, e.g. 600519.")],
    kind: Annotated[
        Literal["top", "float", "count", "trend", "fund"],
        typer.Option("--kind", help="Holder dataset."),
    ] = "top",
    st: Annotated[str | None, typer.Option("--st", help="Start date/time query parameter.")] = None,
    et: Annotated[str | None, typer.Option("--et", help="End date/time query parameter.")] = None,
    licences: BiyingLicencesOption = None,
    base_url: BiyingBaseUrlOption = "https://api.biyingapi.com",
    timeout: BiyingTimeoutOption = DEFAULT_TIMEOUT_SECONDS,
    limit: LimitOption = None,
) -> None:
    """Fetch shareholder and fund-holding datasets through Biying."""

    dataset = {
        "top": "financial-topholder",
        "float": "financial-flowholder",
        "count": "holder-count",
        "trend": "shareholder-trend",
        "fund": "fund-holding",
    }[kind]
    _run_json(
        lambda: _fetch_biying(
            dataset,
            {"symbol": symbol, "market_symbol": symbol, "st": st, "et": et},
            licences=licences,
            base_url=base_url,
            timeout=timeout,
            limit=limit,
        ),
    )


@stock_app.command("dividend")
def stock_dividend(
    symbol: Annotated[str, typer.Option("--symbol", help="A-share code, e.g. 600519.")],
    licences: BiyingLicencesOption = None,
    base_url: BiyingBaseUrlOption = "https://api.biyingapi.com",
    timeout: BiyingTimeoutOption = DEFAULT_TIMEOUT_SECONDS,
    limit: LimitOption = None,
) -> None:
    """Fetch recent dividends through Biying."""

    _run_json(
        lambda: _fetch_biying(
            "dividend",
            {"symbol": symbol},
            licences=licences,
            base_url=base_url,
            timeout=timeout,
            limit=limit,
        ),
    )


@stock_app.command("unlock")
def stock_unlock(
    symbol: Annotated[str, typer.Option("--symbol", help="A-share code, e.g. 600519.")],
    licences: BiyingLicencesOption = None,
    base_url: BiyingBaseUrlOption = "https://api.biyingapi.com",
    timeout: BiyingTimeoutOption = DEFAULT_TIMEOUT_SECONDS,
    limit: LimitOption = None,
) -> None:
    """Fetch restricted-share unlocks through Biying."""

    _run_json(
        lambda: _fetch_biying(
            "unlock",
            {"symbol": symbol},
            licences=licences,
            base_url=base_url,
            timeout=timeout,
            limit=limit,
        ),
    )


@quote_app.command("stock")
def quote_stock(
    symbol: Annotated[str, typer.Option("--symbol", help="A-share code, e.g. 000001.")],
    source: Annotated[
        Literal["biying"],
        typer.Option("--source", help="Data source."),
    ] = "biying",
    licences: BiyingLicencesOption = None,
    base_url: BiyingBaseUrlOption = "https://api.biyingapi.com",
    timeout: BiyingTimeoutOption = DEFAULT_TIMEOUT_SECONDS,
    limit: LimitOption = None,
) -> None:
    """Fetch a realtime stock quote."""

    _ = source
    _run_json(
        lambda: _fetch_biying(
            "stock-realtime",
            {"symbol": symbol},
            licences=licences,
            base_url=base_url,
            timeout=timeout,
            limit=limit,
        ),
    )


@quote_app.command("five")
def quote_five(
    symbol: Annotated[str, typer.Option("--symbol", help="A-share code, e.g. 000001.")],
    licences: BiyingLicencesOption = None,
    base_url: BiyingBaseUrlOption = "https://api.biyingapi.com",
    timeout: BiyingTimeoutOption = DEFAULT_TIMEOUT_SECONDS,
    limit: LimitOption = None,
) -> None:
    """Fetch level-5 order book data."""

    _run_json(
        lambda: _fetch_biying(
            "stock-five",
            {"symbol": symbol},
            licences=licences,
            base_url=base_url,
            timeout=timeout,
            limit=limit,
        ),
    )


@quote_app.command("ticks")
def quote_ticks(
    symbol: Annotated[str, typer.Option("--symbol", help="A-share code, e.g. 000001.")],
    licences: BiyingLicencesOption = None,
    base_url: BiyingBaseUrlOption = "https://api.biyingapi.com",
    timeout: BiyingTimeoutOption = DEFAULT_TIMEOUT_SECONDS,
    limit: LimitOption = None,
) -> None:
    """Fetch current-day tick trades."""

    _run_json(
        lambda: _fetch_biying(
            "stock-ticks",
            {"symbol": symbol},
            licences=licences,
            base_url=base_url,
            timeout=timeout,
            limit=limit,
        ),
    )


@quote_app.command("flow")
def quote_flow(
    symbol: Annotated[str, typer.Option("--symbol", help="A-share code, e.g. 000001.")],
    st: Annotated[str | None, typer.Option("--st", help="Start date/time query parameter.")] = None,
    et: Annotated[str | None, typer.Option("--et", help="End date/time query parameter.")] = None,
    lt: Annotated[
        int | None,
        typer.Option("--lt", help="Latest row count query parameter."),
    ] = None,
    licences: BiyingLicencesOption = None,
    base_url: BiyingBaseUrlOption = "https://api.biyingapi.com",
    timeout: BiyingTimeoutOption = DEFAULT_TIMEOUT_SECONDS,
    limit: LimitOption = None,
) -> None:
    """Fetch stock capital-flow data."""

    _run_json(
        lambda: _fetch_biying(
            "fund-flow",
            {"symbol": symbol, "st": st, "et": et, "lt": lt},
            licences=licences,
            base_url=base_url,
            timeout=timeout,
            limit=limit,
        ),
    )


@quote_app.command("pool")
def quote_pool(
    kind: Annotated[
        Literal["limit-up", "limit-down", "strong", "new-stock", "limit-break"],
        typer.Option("--kind", help="Stock pool kind."),
    ],
    date: Annotated[str, typer.Option("--date", help="Trading date, e.g. 2024-01-10.")],
    licences: BiyingLicencesOption = None,
    base_url: BiyingBaseUrlOption = "https://api.biyingapi.com",
    timeout: BiyingTimeoutOption = DEFAULT_TIMEOUT_SECONDS,
    limit: LimitOption = None,
) -> None:
    """Fetch event-driven stock pools."""

    dataset = {
        "limit-up": "limit-up-pool",
        "limit-down": "limit-down-pool",
        "strong": "strong-pool",
        "new-stock": "new-stock-pool",
        "limit-break": "limit-break-pool",
    }[kind]
    _run_json(
        lambda: _fetch_biying(
            dataset,
            {"date": date},
            licences=licences,
            base_url=base_url,
            timeout=timeout,
            limit=limit,
        ),
    )


@quote_app.command("exchange-summary")
def quote_exchange_summary(
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


@sector_app.command("list")
def sector_list(
    source: Annotated[
        Literal["baostock", "biying"],
        typer.Option("--source", help="Data source."),
    ] = "baostock",
    licences: BiyingLicencesOption = None,
    base_url: BiyingBaseUrlOption = "https://api.biyingapi.com",
    timeout: BiyingTimeoutOption = DEFAULT_TIMEOUT_SECONDS,
    limit: LimitOption = None,
    no_proxy: NoProxyOption = False,
    ipv4: Ipv4Option = False,
) -> None:
    """Fetch industry or sector lists."""

    if source == "biying":
        _run_json(
            lambda: _fetch_biying(
                "concept-tree",
                {},
                licences=licences,
                base_url=base_url,
                timeout=timeout,
                limit=limit,
            ),
        )
        return

    _run_json(lambda: fetch_industry_list(limit=limit, no_proxy=no_proxy, ipv4=ipv4))


@sector_app.command("stocks")
def sector_stocks(
    code: Annotated[
        str,
        typer.Option("--code", help="Biying index, industry, or concept code."),
    ],
    licences: BiyingLicencesOption = None,
    base_url: BiyingBaseUrlOption = "https://api.biyingapi.com",
    timeout: BiyingTimeoutOption = DEFAULT_TIMEOUT_SECONDS,
    limit: LimitOption = None,
) -> None:
    """Fetch stocks for one Biying index, industry, or concept code."""

    _run_json(
        lambda: _fetch_biying(
            "concept-stocks",
            {"code": code},
            licences=licences,
            base_url=base_url,
            timeout=timeout,
            limit=limit,
        ),
    )


@sector_app.command("concepts")
def sector_concepts(
    symbol: Annotated[str, typer.Option("--symbol", help="A-share code, e.g. 000001.")],
    licences: BiyingLicencesOption = None,
    base_url: BiyingBaseUrlOption = "https://api.biyingapi.com",
    timeout: BiyingTimeoutOption = DEFAULT_TIMEOUT_SECONDS,
    limit: LimitOption = None,
) -> None:
    """Fetch index, industry, and concepts for one stock through Biying."""

    _run_json(
        lambda: _fetch_biying(
            "stock-concepts",
            {"symbol": symbol},
            licences=licences,
            base_url=base_url,
            timeout=timeout,
            limit=limit,
        ),
    )


@index_app.command("list")
def index_list(
    licences: BiyingLicencesOption = None,
    base_url: BiyingBaseUrlOption = "https://api.biyingapi.com",
    timeout: BiyingTimeoutOption = DEFAULT_TIMEOUT_SECONDS,
    limit: LimitOption = None,
) -> None:
    """Fetch major A-share index list through Biying."""

    _run_json(
        lambda: _fetch_biying(
            "index-list",
            {},
            licences=licences,
            base_url=base_url,
            timeout=timeout,
            limit=limit,
        ),
    )


@index_app.command("quote")
def index_quote(
    index: Annotated[str, typer.Option("--index", help="Index symbol, e.g. 000001.SH.")],
    licences: BiyingLicencesOption = None,
    base_url: BiyingBaseUrlOption = "https://api.biyingapi.com",
    timeout: BiyingTimeoutOption = DEFAULT_TIMEOUT_SECONDS,
    limit: LimitOption = None,
) -> None:
    """Fetch a realtime index quote through Biying."""

    _run_json(
        lambda: _fetch_biying(
            "index-realtime",
            {"index": index},
            licences=licences,
            base_url=base_url,
            timeout=timeout,
            limit=limit,
        ),
    )


@index_app.command("history")
def index_history(
    index: Annotated[str, typer.Option("--index", help="Index symbol, e.g. 000001.SH.")],
    period: Annotated[str, typer.Option("--period", help="Biying bar period.")] = "d",
    st: Annotated[str | None, typer.Option("--st", help="Start date/time query parameter.")] = None,
    et: Annotated[str | None, typer.Option("--et", help="End date/time query parameter.")] = None,
    lt: Annotated[
        int | None,
        typer.Option("--lt", help="Latest row count query parameter."),
    ] = None,
    licences: BiyingLicencesOption = None,
    base_url: BiyingBaseUrlOption = "https://api.biyingapi.com",
    timeout: BiyingTimeoutOption = DEFAULT_TIMEOUT_SECONDS,
    limit: LimitOption = None,
) -> None:
    """Fetch historical index bars through Biying."""

    _run_json(
        lambda: _fetch_biying(
            "index-history",
            {"index": index, "period": period, "st": st, "et": et, "lt": lt},
            licences=licences,
            base_url=base_url,
            timeout=timeout,
            limit=limit,
        ),
    )


@fund_app.command("list")
def fund_list(
    licences: BiyingLicencesOption = None,
    base_url: BiyingBaseUrlOption = "https://api.biyingapi.com",
    timeout: BiyingTimeoutOption = DEFAULT_TIMEOUT_SECONDS,
    limit: LimitOption = None,
) -> None:
    """Fetch Shanghai and Shenzhen fund list through Biying."""

    _run_json(
        lambda: _fetch_biying(
            "fund-list",
            {},
            licences=licences,
            base_url=base_url,
            timeout=timeout,
            limit=limit,
        ),
    )


@fund_app.command("etf-list")
def fund_etf_list(
    licences: BiyingLicencesOption = None,
    base_url: BiyingBaseUrlOption = "https://api.biyingapi.com",
    timeout: BiyingTimeoutOption = DEFAULT_TIMEOUT_SECONDS,
    limit: LimitOption = None,
) -> None:
    """Fetch ETF fund list through Biying."""

    _run_json(
        lambda: _fetch_biying(
            "etf-list",
            {},
            licences=licences,
            base_url=base_url,
            timeout=timeout,
            limit=limit,
        ),
    )


@fund_app.command("quote")
def fund_quote(
    fund: Annotated[str, typer.Option("--fund", help="Fund code, e.g. 159001.")],
    licences: BiyingLicencesOption = None,
    base_url: BiyingBaseUrlOption = "https://api.biyingapi.com",
    timeout: BiyingTimeoutOption = DEFAULT_TIMEOUT_SECONDS,
    limit: LimitOption = None,
) -> None:
    """Fetch a realtime fund quote through Biying."""

    _run_json(
        lambda: _fetch_biying(
            "fund-realtime",
            {"fund": fund},
            licences=licences,
            base_url=base_url,
            timeout=timeout,
            limit=limit,
        ),
    )


def _fetch_biying(
    dataset: str,
    params: dict[str, str | int | None],
    *,
    licences: str | None,
    base_url: str,
    timeout: float,
    limit: int | None,
) -> dict[str, object]:
    return fetch_biying_dataset(
        dataset=dataset,
        params=params,
        licences_value=licences,
        base_url=base_url,
        timeout=timeout,
        limit=limit,
    )


def _biying_period(period: str) -> str:
    return {"daily": "d", "weekly": "w", "monthly": "m"}.get(period, period)


def _biying_adjust(adjust: str) -> str:
    return {"none": "n", "qfq": "q", "hfq": "h"}.get(adjust, adjust)


def _raise_value_error(message: str) -> dict[str, object]:
    raise ValueError(message)


def _run_json(operation: Callable[[], dict[str, object]]) -> None:
    """Run an operation and emit a single JSON object."""

    try:
        _echo_json(operation())
    except Exception as exc:
        _echo_json({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}})
        raise typer.Exit(1) from exc


def _exit_with_error(exc: AMStockError) -> None:
    _echo_json(
        {
            "ok": False,
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }
    )
    raise typer.Exit(1) from exc


def _echo_json(payload: dict[str, object]) -> None:
    typer.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True))


app.add_typer(db_app, name="db")
app.add_typer(stock_app, name="stock")
app.add_typer(quote_app, name="quote")
app.add_typer(sector_app, name="sector")
app.add_typer(index_app, name="index")
app.add_typer(fund_app, name="fund")
app.add_typer(sources_app, name="sources")
app.add_typer(portfolio_app, name="portfolio")


def main() -> None:
    """Run the command-line application."""

    app()
