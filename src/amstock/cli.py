"""Command-line entry point."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Annotated, Literal

import typer

from amstock import __version__
from amstock.akshare_io import configure_network, dataframe_payload
from amstock.biying_io import DEFAULT_TIMEOUT_SECONDS, fetch_biying_dataset
from amstock.config import amstock_home, config_path, default_config_toml, resolve_config_path
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
config_app = typer.Typer(no_args_is_help=True)
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


@config_app.command("path")
def config_path_command() -> None:
    """Print AMStock home and config paths."""

    home = amstock_home()
    primary = config_path(home)
    try:
        active = resolve_config_path(home)
    except AMStockError:
        active = primary
    _echo_json(
        {
            "ok": True,
            "amstock_home": str(home),
            "config_path": str(primary),
            "active_config_path": str(active),
            "exists": active.exists(),
        }
    )


@config_app.command("init")
def config_init(
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite an existing config file."),
    ] = False,
) -> None:
    """Create AMSTOCK_HOME/config/config.toml."""

    home = amstock_home()
    path = config_path(home)
    if path.exists() and not force:
        _echo_json(
            {
                "ok": True,
                "created": False,
                "config_path": str(path),
                "message": "config already exists",
            }
        )
        return

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(default_config_toml(), encoding="utf-8")
    except OSError as exc:
        _echo_json(
            {
                "ok": False,
                "error": {
                    "type": type(exc).__name__,
                    "message": f"could not write config file: {path}: {exc}",
                },
            }
        )
        raise typer.Exit(1) from exc

    _echo_json({"ok": True, "created": True, "config_path": str(path)})


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


@stock_app.command("profile")
def stock_profile(
    symbol: Annotated[str, typer.Option("--symbol", help="A-share code, e.g. 600519.")],
    licences: BiyingLicencesOption = None,
    base_url: BiyingBaseUrlOption = "https://api.biyingapi.com",
    timeout: BiyingTimeoutOption = DEFAULT_TIMEOUT_SECONDS,
    limit: LimitOption = None,
) -> None:
    """Fetch company profile through Biying."""

    _run_json(
        lambda: _fetch_biying(
            "company-profile",
            {"symbol": symbol},
            licences=licences,
            base_url=base_url,
            timeout=timeout,
            limit=limit,
        ),
    )


@stock_app.command("concepts")
def stock_concepts(
    symbol: Annotated[str, typer.Option("--symbol", help="A-share code, e.g. 000063.")],
    licences: BiyingLicencesOption = None,
    base_url: BiyingBaseUrlOption = "https://api.biyingapi.com",
    timeout: BiyingTimeoutOption = DEFAULT_TIMEOUT_SECONDS,
    limit: LimitOption = None,
) -> None:
    """Fetch related concepts, industries, and indexes for one stock."""

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


@stock_app.command("indexes")
def stock_indexes(
    symbol: Annotated[str, typer.Option("--symbol", help="A-share code, e.g. 000063.")],
    licences: BiyingLicencesOption = None,
    base_url: BiyingBaseUrlOption = "https://api.biyingapi.com",
    timeout: BiyingTimeoutOption = DEFAULT_TIMEOUT_SECONDS,
    limit: LimitOption = None,
) -> None:
    """Fetch indexes that include one stock."""

    _run_json(
        lambda: _fetch_biying(
            "stock-indexes",
            {"symbol": symbol},
            licences=licences,
            base_url=base_url,
            timeout=timeout,
            limit=limit,
        ),
    )


@stock_app.command("offering")
def stock_offering(
    symbol: Annotated[str, typer.Option("--symbol", help="A-share code, e.g. 000063.")],
    licences: BiyingLicencesOption = None,
    base_url: BiyingBaseUrlOption = "https://api.biyingapi.com",
    timeout: BiyingTimeoutOption = DEFAULT_TIMEOUT_SECONDS,
    limit: LimitOption = None,
) -> None:
    """Fetch recent secondary offerings through Biying."""

    _run_json(
        lambda: _fetch_biying(
            "secondary-offering",
            {"symbol": symbol},
            licences=licences,
            base_url=base_url,
            timeout=timeout,
            limit=limit,
        ),
    )


@stock_app.command("quarterly")
def stock_quarterly(
    symbol: Annotated[str, typer.Option("--symbol", help="A-share code, e.g. 000063.")],
    kind: Annotated[
        Literal["profit", "cashflow"],
        typer.Option("--kind", help="Quarterly dataset."),
    ] = "profit",
    licences: BiyingLicencesOption = None,
    base_url: BiyingBaseUrlOption = "https://api.biyingapi.com",
    timeout: BiyingTimeoutOption = DEFAULT_TIMEOUT_SECONDS,
    limit: LimitOption = None,
) -> None:
    """Fetch recent quarterly profit or cash-flow data through Biying."""

    dataset = {"profit": "quarterly-profit", "cashflow": "quarterly-cashflow"}[kind]
    _run_json(
        lambda: _fetch_biying(
            dataset,
            {"symbol": symbol},
            licences=licences,
            base_url=base_url,
            timeout=timeout,
            limit=limit,
        ),
    )


@stock_app.command("management")
def stock_management(
    symbol: Annotated[str, typer.Option("--symbol", help="A-share code, e.g. 000063.")],
    kind: Annotated[
        Literal["management", "directors", "supervisors"],
        typer.Option("--kind", help="Governance member dataset."),
    ] = "management",
    licences: BiyingLicencesOption = None,
    base_url: BiyingBaseUrlOption = "https://api.biyingapi.com",
    timeout: BiyingTimeoutOption = DEFAULT_TIMEOUT_SECONDS,
    limit: LimitOption = None,
) -> None:
    """Fetch historical management, director, or supervisor members."""

    _run_json(
        lambda: _fetch_biying(
            kind,
            {"symbol": symbol},
            licences=licences,
            base_url=base_url,
            timeout=timeout,
            limit=limit,
        ),
    )


@stock_app.command("indicators")
def stock_indicators(
    symbol: Annotated[str, typer.Option("--symbol", help="A-share code, e.g. 000063.")],
    st: Annotated[str | None, typer.Option("--st", help="Start date/time query parameter.")] = None,
    et: Annotated[str | None, typer.Option("--et", help="End date/time query parameter.")] = None,
    licences: BiyingLicencesOption = None,
    base_url: BiyingBaseUrlOption = "https://api.biyingapi.com",
    timeout: BiyingTimeoutOption = DEFAULT_TIMEOUT_SECONDS,
    limit: LimitOption = None,
) -> None:
    """Fetch quote indicator data through Biying."""

    _run_json(
        lambda: _fetch_biying(
            "quote-indicators",
            {"market_symbol": symbol, "st": st, "et": et},
            licences=licences,
            base_url=base_url,
            timeout=timeout,
            limit=limit,
        ),
    )


@stock_app.command("tech")
def stock_tech(
    symbol: Annotated[str, typer.Option("--symbol", help="A-share code, e.g. 000063.")],
    indicator: Annotated[
        Literal["macd", "ma", "boll", "kdj"],
        typer.Option("--indicator", help="Technical indicator."),
    ],
    period: Annotated[str, typer.Option("--period", help="Biying bar period.")] = "d",
    adjust: Annotated[str, typer.Option("--adjust", help="Biying adjustment type.")] = "n",
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
    """Fetch stock technical indicators through Biying."""

    _run_json(
        lambda: _fetch_biying(
            f"stock-tech-{indicator}",
            {
                "market_symbol": symbol,
                "period": period,
                "adjust": adjust,
                "st": st,
                "et": et,
                "lt": lt,
            },
            licences=licences,
            base_url=base_url,
            timeout=timeout,
            limit=limit,
        ),
    )


@stock_app.command("balance")
def stock_balance(
    symbol: Annotated[str, typer.Option("--symbol", help="A-share code, e.g. 000063.")],
    st: Annotated[str | None, typer.Option("--st", help="Start date/time query parameter.")] = None,
    et: Annotated[str | None, typer.Option("--et", help="End date/time query parameter.")] = None,
    licences: BiyingLicencesOption = None,
    base_url: BiyingBaseUrlOption = "https://api.biyingapi.com",
    timeout: BiyingTimeoutOption = DEFAULT_TIMEOUT_SECONDS,
    limit: LimitOption = None,
) -> None:
    """Fetch Biying balance sheet."""

    _run_json(
        lambda: _fetch_biying(
            "financial-balance",
            {"market_symbol": symbol, "st": st, "et": et},
            licences=licences,
            base_url=base_url,
            timeout=timeout,
            limit=limit,
        ),
    )


@stock_app.command("income")
def stock_income(
    symbol: Annotated[str, typer.Option("--symbol", help="A-share code, e.g. 000063.")],
    st: Annotated[str | None, typer.Option("--st", help="Start date/time query parameter.")] = None,
    et: Annotated[str | None, typer.Option("--et", help="End date/time query parameter.")] = None,
    licences: BiyingLicencesOption = None,
    base_url: BiyingBaseUrlOption = "https://api.biyingapi.com",
    timeout: BiyingTimeoutOption = DEFAULT_TIMEOUT_SECONDS,
    limit: LimitOption = None,
) -> None:
    """Fetch Biying income statement."""

    _run_json(
        lambda: _fetch_biying(
            "financial-income",
            {"market_symbol": symbol, "st": st, "et": et},
            licences=licences,
            base_url=base_url,
            timeout=timeout,
            limit=limit,
        ),
    )


@stock_app.command("cashflow")
def stock_cashflow(
    symbol: Annotated[str, typer.Option("--symbol", help="A-share code, e.g. 000063.")],
    st: Annotated[str | None, typer.Option("--st", help="Start date/time query parameter.")] = None,
    et: Annotated[str | None, typer.Option("--et", help="End date/time query parameter.")] = None,
    licences: BiyingLicencesOption = None,
    base_url: BiyingBaseUrlOption = "https://api.biyingapi.com",
    timeout: BiyingTimeoutOption = DEFAULT_TIMEOUT_SECONDS,
    limit: LimitOption = None,
) -> None:
    """Fetch Biying cash-flow statement."""

    _run_json(
        lambda: _fetch_biying(
            "financial-cashflow",
            {"market_symbol": symbol, "st": st, "et": et},
            licences=licences,
            base_url=base_url,
            timeout=timeout,
            limit=limit,
        ),
    )


@stock_app.command("financial-summary")
def stock_financial_summary(
    symbol: Annotated[str, typer.Option("--symbol", help="A-share code, e.g. 000063.")],
    licences: BiyingLicencesOption = None,
    base_url: BiyingBaseUrlOption = "https://api.biyingapi.com",
    timeout: BiyingTimeoutOption = DEFAULT_TIMEOUT_SECONDS,
    limit: LimitOption = None,
) -> None:
    """Fetch Biying financial indicator summary."""

    _run_json(
        lambda: _fetch_biying(
            "financial-indicator-summary",
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


@quote_app.command("flow-summary")
def quote_flow_summary(
    symbol: Annotated[str, typer.Option("--symbol", help="A-share code, e.g. 000001.")],
    days: Annotated[int, typer.Option("--days", help="Latest trading days to summarize.")] = 5,
    st: Annotated[str | None, typer.Option("--st", help="Start date/time query parameter.")] = None,
    et: Annotated[str | None, typer.Option("--et", help="End date/time query parameter.")] = None,
    licences: BiyingLicencesOption = None,
    base_url: BiyingBaseUrlOption = "https://api.biyingapi.com",
    timeout: BiyingTimeoutOption = DEFAULT_TIMEOUT_SECONDS,
) -> None:
    """Summarize recent stock capital-flow data from Biying."""

    _run_json(
        lambda: _flow_summary_payload(
            symbol=symbol,
            days=days,
            st=st,
            et=et,
            raw=_fetch_biying(
                "fund-flow",
                {"symbol": symbol, "st": st, "et": et, "lt": max(days, 10)},
                licences=licences,
                base_url=base_url,
                timeout=timeout,
                limit=None,
            ),
        ),
    )


@quote_app.command("batch")
def quote_batch(
    symbols: Annotated[
        str,
        typer.Option("--symbols", help="Comma-separated stock codes, up to Biying API limit."),
    ],
    licences: BiyingLicencesOption = None,
    base_url: BiyingBaseUrlOption = "https://api.biyingapi.com",
    timeout: BiyingTimeoutOption = DEFAULT_TIMEOUT_SECONDS,
    limit: LimitOption = None,
) -> None:
    """Fetch realtime quotes for multiple stocks."""

    _run_json(
        lambda: _fetch_biying(
            "stock-realtime-more",
            {"stock_codes": symbols},
            licences=licences,
            base_url=base_url,
            timeout=timeout,
            limit=limit,
        ),
    )


@quote_app.command("all")
def quote_all(
    feed: Annotated[
        Literal["broker", "network"],
        typer.Option("--feed", help="Biying all-market realtime feed."),
    ] = "network",
    licences: BiyingLicencesOption = None,
    base_url: BiyingBaseUrlOption = "https://api.biyingapi.com",
    timeout: BiyingTimeoutOption = DEFAULT_TIMEOUT_SECONDS,
    limit: LimitOption = None,
) -> None:
    """Fetch all-market realtime stock quotes."""

    _run_json(
        lambda: _fetch_quote_all(
            feed=feed,
            licences=licences,
            base_url=base_url,
            timeout=timeout,
            limit=limit,
        ),
    )


@quote_app.command("intraday")
def quote_intraday(
    symbol: Annotated[str, typer.Option("--symbol", help="A-share code, e.g. 000063.")],
    period: Annotated[str, typer.Option("--period", help="Biying bar period.")] = "d",
    adjust: Annotated[str, typer.Option("--adjust", help="Biying adjustment type.")] = "n",
    lt: Annotated[
        int | None,
        typer.Option("--lt", help="Latest row count query parameter."),
    ] = None,
    licences: BiyingLicencesOption = None,
    base_url: BiyingBaseUrlOption = "https://api.biyingapi.com",
    timeout: BiyingTimeoutOption = DEFAULT_TIMEOUT_SECONDS,
    limit: LimitOption = None,
) -> None:
    """Fetch latest stock intraday or bar data."""

    _run_json(
        lambda: _fetch_biying(
            "stock-latest",
            {"market_symbol": symbol, "period": period, "adjust": adjust, "lt": lt},
            licences=licences,
            base_url=base_url,
            timeout=timeout,
            limit=limit,
        ),
    )


@quote_app.command("history-intraday")
def quote_history_intraday(
    symbol: Annotated[str, typer.Option("--symbol", help="A-share code, e.g. 000063.")],
    period: Annotated[str, typer.Option("--period", help="Biying bar period.")] = "d",
    adjust: Annotated[str, typer.Option("--adjust", help="Biying adjustment type.")] = "n",
    st: Annotated[str | None, typer.Option("--st", help="Start date/time query parameter.")] = None,
    et: Annotated[str | None, typer.Option("--et", help="End date/time query parameter.")] = None,
    date: Annotated[
        str | None,
        typer.Option("--date", help="Convenience trading date used for st and et."),
    ] = None,
    lt: Annotated[
        int | None,
        typer.Option("--lt", help="Latest row count query parameter."),
    ] = None,
    licences: BiyingLicencesOption = None,
    base_url: BiyingBaseUrlOption = "https://api.biyingapi.com",
    timeout: BiyingTimeoutOption = DEFAULT_TIMEOUT_SECONDS,
    limit: LimitOption = None,
) -> None:
    """Fetch historical stock intraday or bar data."""

    _run_json(
        lambda: _fetch_biying(
            "stock-history",
            {
                "market_symbol": symbol,
                "period": period,
                "adjust": adjust,
                "st": st or date,
                "et": et or date,
                "lt": lt,
            },
            licences=licences,
            base_url=base_url,
            timeout=timeout,
            limit=limit,
        ),
    )


@quote_app.command("limit-price-history")
def quote_limit_price_history(
    symbol: Annotated[str, typer.Option("--symbol", help="A-share code, e.g. 000063.")],
    st: Annotated[str | None, typer.Option("--st", help="Start date/time query parameter.")] = None,
    et: Annotated[str | None, typer.Option("--et", help="End date/time query parameter.")] = None,
    licences: BiyingLicencesOption = None,
    base_url: BiyingBaseUrlOption = "https://api.biyingapi.com",
    timeout: BiyingTimeoutOption = DEFAULT_TIMEOUT_SECONDS,
    limit: LimitOption = None,
) -> None:
    """Fetch historical limit-up and limit-down prices."""

    _run_json(
        lambda: _fetch_biying(
            "stop-price-history",
            {"market_symbol": symbol, "st": st, "et": et},
            licences=licences,
            base_url=base_url,
            timeout=timeout,
            limit=limit,
        ),
    )


@quote_app.command("breadth")
def quote_breadth(
    feed: Annotated[
        Literal["broker", "network"],
        typer.Option("--feed", help="Biying all-market realtime feed."),
    ] = "network",
    licences: BiyingLicencesOption = None,
    base_url: BiyingBaseUrlOption = "https://api.biyingapi.com",
    timeout: BiyingTimeoutOption = DEFAULT_TIMEOUT_SECONDS,
) -> None:
    """Calculate market breadth from all-market realtime quotes."""

    _run_json(
        lambda: _breadth_payload(
            _fetch_quote_all(
                feed=feed,
                licences=licences,
                base_url=base_url,
                timeout=timeout,
                limit=None,
            )
        ),
    )


@quote_app.command("sentiment")
def quote_sentiment(
    date: Annotated[str, typer.Option("--date", help="Trading date, e.g. 2024-01-10.")],
    feed: Annotated[
        Literal["broker", "network"],
        typer.Option("--feed", help="Biying all-market realtime feed for breadth."),
    ] = "network",
    licences: BiyingLicencesOption = None,
    base_url: BiyingBaseUrlOption = "https://api.biyingapi.com",
    timeout: BiyingTimeoutOption = DEFAULT_TIMEOUT_SECONDS,
) -> None:
    """Calculate a market sentiment snapshot from stock pools and breadth."""

    _run_json(
        lambda: _sentiment_payload(
            date=date,
            feed=feed,
            licences=licences,
            base_url=base_url,
            timeout=timeout,
        ),
    )


@quote_app.command("pool")
def quote_pool(
    kind: Annotated[
        Literal["limit-up", "limit-down", "strong", "new-stock", "limit-break", "failed-limit-up"],
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
        "failed-limit-up": "limit-break-pool",
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


@sector_app.command("flow")
def sector_flow(
    kind: Annotated[
        Literal["industry", "concept"],
        typer.Option("--kind", help="Sector flow kind."),
    ] = "industry",
    period: Annotated[
        Literal["realtime", "3d", "5d", "10d", "20d"],
        typer.Option("--period", help="Ranking period."),
    ] = "realtime",
    limit: LimitOption = None,
    no_proxy: NoProxyOption = False,
    ipv4: Ipv4Option = False,
) -> None:
    """Fetch sector fund-flow rankings from the tested THS AKShare source."""

    function = {
        "industry": "stock_fund_flow_industry",
        "concept": "stock_fund_flow_concept",
    }[kind]
    _run_json(
        lambda: _akshare_dataframe(
            function,
            {
                "symbol": {
                    "realtime": "即时",
                    "3d": "3日排行",
                    "5d": "5日排行",
                    "10d": "10日排行",
                    "20d": "20日排行",
                }[period],
            },
            limit=limit,
            no_proxy=no_proxy,
            ipv4=ipv4,
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
    index: Annotated[
        str,
        typer.Option("--index", "--symbol", help="Index symbol, e.g. 000001.SH."),
    ],
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
    index: Annotated[
        str,
        typer.Option("--index", "--symbol", help="Index symbol, e.g. 000001.SH."),
    ],
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


@index_app.command("intraday")
def index_intraday(
    index: Annotated[
        str,
        typer.Option("--index", "--symbol", help="Index symbol, e.g. 000001.SH."),
    ],
    period: Annotated[str, typer.Option("--period", help="Biying bar period.")] = "d",
    lt: Annotated[
        int | None,
        typer.Option("--lt", help="Latest row count query parameter."),
    ] = None,
    licences: BiyingLicencesOption = None,
    base_url: BiyingBaseUrlOption = "https://api.biyingapi.com",
    timeout: BiyingTimeoutOption = DEFAULT_TIMEOUT_SECONDS,
    limit: LimitOption = None,
) -> None:
    """Fetch latest index intraday or bar data."""

    _run_json(
        lambda: _fetch_biying(
            "index-latest",
            {"index": index, "period": period, "lt": lt},
            licences=licences,
            base_url=base_url,
            timeout=timeout,
            limit=limit,
        ),
    )


@index_app.command("tech")
def index_tech(
    index: Annotated[
        str,
        typer.Option("--index", "--symbol", help="Index symbol, e.g. 000001.SH."),
    ],
    indicator: Annotated[
        Literal["macd", "ma", "boll", "kdj"],
        typer.Option("--indicator", help="Technical indicator."),
    ],
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
    """Fetch index technical indicators through Biying."""

    _run_json(
        lambda: _fetch_biying(
            f"index-tech-{indicator}",
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
    fund: Annotated[str, typer.Option("--fund", "--symbol", help="Fund code, e.g. 159001.")],
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


@fund_app.command("share-change")
def fund_share_change(
    exchange: Annotated[
        Literal["sse", "szse"],
        typer.Option("--exchange", help="Exchange to query."),
    ],
    date: Annotated[
        str | None,
        typer.Option("--date", help="Single date in YYYYMMDD format."),
    ] = None,
    start_date: Annotated[
        str | None,
        typer.Option("--start-date", help="SZSE start date in YYYYMMDD format."),
    ] = None,
    end_date: Annotated[
        str | None,
        typer.Option("--end-date", help="SZSE end date in YYYYMMDD format."),
    ] = None,
    limit: LimitOption = None,
    no_proxy: NoProxyOption = False,
    ipv4: Ipv4Option = False,
) -> None:
    """Fetch ETF share data from tested SSE/SZSE AKShare sources."""

    if exchange == "sse":
        _run_json(
            lambda: _akshare_dataframe(
                "fund_etf_scale_sse",
                {"date": date or ""},
                limit=limit,
                no_proxy=no_proxy,
                ipv4=ipv4,
            )
        )
        return

    resolved_start = start_date or date
    resolved_end = end_date or date or resolved_start
    params: dict[str, object] = {"symbol": "ETF"}
    if resolved_start:
        params["start_date"] = resolved_start
    if resolved_end:
        params["end_date"] = resolved_end
    _run_json(
        lambda: _akshare_dataframe(
            "fund_scale_daily_szse",
            params,
            limit=limit,
            no_proxy=no_proxy,
            ipv4=ipv4,
        )
    )


@fund_app.command("holdings")
def fund_holdings(
    fund: Annotated[str, typer.Option("--fund", "--symbol", help="Fund code, e.g. 159995.")],
    year: Annotated[str, typer.Option("--year", help="Report year, e.g. 2024.")] = "2024",
    limit: LimitOption = None,
    no_proxy: NoProxyOption = False,
    ipv4: Ipv4Option = False,
) -> None:
    """Fetch one fund's portfolio holdings from the tested Eastmoney AKShare source."""

    _run_json(
        lambda: _akshare_dataframe(
            "fund_portfolio_hold_em",
            {"symbol": fund, "date": year},
            limit=limit,
            no_proxy=no_proxy,
            ipv4=ipv4,
        )
    )


@fund_app.command("holding-summary")
def fund_holding_summary(
    date: Annotated[str, typer.Option("--date", help="Report date in YYYYMMDD format.")],
    limit: LimitOption = None,
    no_proxy: NoProxyOption = False,
    ipv4: Ipv4Option = False,
) -> None:
    """Fetch market-level fund stock-holding summary from the tested CNInfo source."""

    _run_json(
        lambda: _akshare_dataframe(
            "fund_report_stock_cninfo",
            {"date": date},
            limit=limit,
            no_proxy=no_proxy,
            ipv4=ipv4,
        )
    )


def _fetch_quote_all(
    *,
    feed: str,
    licences: str | None,
    base_url: str,
    timeout: float,
    limit: int | None,
) -> dict[str, object]:
    dataset = {"broker": "stock-all-broker", "network": "stock-all-network"}[feed]
    return _fetch_biying(
        dataset,
        {},
        licences=licences,
        base_url=base_url,
        timeout=timeout,
        limit=limit,
    )


def _breadth_payload(payload: dict[str, object]) -> dict[str, object]:
    records = _payload_records(payload)
    changes = [
        change
        for record in records
        if (change := _record_change_percent(record)) is not None
    ]
    sorted_changes = sorted(changes)
    summary = {
        "total": len(records),
        "with_change_percent": len(changes),
        "up": sum(1 for value in changes if value > 0),
        "down": sum(1 for value in changes if value < 0),
        "flat": sum(1 for value in changes if value == 0),
        "up_gt_5": sum(1 for value in changes if value > 5),
        "down_lt_minus_5": sum(1 for value in changes if value < -5),
        "up_gte_9": sum(1 for value in changes if value >= 9),
        "down_lte_minus_9": sum(1 for value in changes if value <= -9),
        "median_change_percent": _median(sorted_changes),
    }
    return {
        "ok": True,
        "source": "amstock",
        "function": "quote-breadth",
        "params": {"source_dataset": payload.get("dataset")},
        "rows": 1,
        "returned_rows": 1,
        "columns": list(summary),
        "data": [summary],
        "raw_rows": payload.get("rows"),
    }


def _sentiment_payload(
    *,
    date: str,
    feed: str,
    licences: str | None,
    base_url: str,
    timeout: float,
) -> dict[str, object]:
    pool_payloads = {
        "limit_up": _fetch_biying(
            "limit-up-pool",
            {"date": date},
            licences=licences,
            base_url=base_url,
            timeout=timeout,
            limit=None,
        ),
        "limit_down": _fetch_biying(
            "limit-down-pool",
            {"date": date},
            licences=licences,
            base_url=base_url,
            timeout=timeout,
            limit=None,
        ),
        "strong": _fetch_biying(
            "strong-pool",
            {"date": date},
            licences=licences,
            base_url=base_url,
            timeout=timeout,
            limit=None,
        ),
        "limit_break": _fetch_biying(
            "limit-break-pool",
            {"date": date},
            licences=licences,
            base_url=base_url,
            timeout=timeout,
            limit=None,
        ),
    }
    breadth = _breadth_payload(
        _fetch_quote_all(
            feed=feed,
            licences=licences,
            base_url=base_url,
            timeout=timeout,
            limit=None,
        )
    )
    limit_up_records = _payload_records(pool_payloads["limit_up"])
    limit_break_count = _payload_row_count(pool_payloads["limit_break"])
    limit_up_count = _payload_row_count(pool_payloads["limit_up"])
    board_attempts = limit_up_count + limit_break_count
    summary = {
        "date": date,
        "limit_up": limit_up_count,
        "limit_down": _payload_row_count(pool_payloads["limit_down"]),
        "strong": _payload_row_count(pool_payloads["strong"]),
        "limit_break": limit_break_count,
        "limit_break_rate": (
            None if board_attempts == 0 else round(limit_break_count / board_attempts, 6)
        ),
        "highest_board_count": _max_numeric_field(limit_up_records, ("lbc", "连板数")),
        "breadth": _payload_records(breadth)[0] if _payload_records(breadth) else {},
    }
    return {
        "ok": True,
        "source": "amstock",
        "function": "quote-sentiment",
        "params": {"date": date, "feed": feed},
        "rows": 1,
        "returned_rows": 1,
        "columns": list(summary),
        "data": [summary],
    }


def _flow_summary_payload(
    *,
    symbol: str,
    days: int,
    st: str | None,
    et: str | None,
    raw: dict[str, object],
) -> dict[str, object]:
    if days <= 0:
        raise ValueError("--days must be greater than 0")

    records = _recent_records(_payload_records(raw), days)
    windows = {
        "main_net_1d": _window_main_net(records, 1),
        "main_net_3d": _window_main_net(records, 3),
        "main_net_5d": _window_main_net(records, 5),
        "main_net_10d": _window_main_net(records, 10),
    }
    super_large_net = sum(_flow_net(record, "td") for record in records)
    large_net = sum(_flow_net(record, "dd") for record in records)
    medium_net = sum(_flow_net(record, "zd") for record in records)
    small_net = sum(_flow_net(record, "xd") for record in records)
    main_net = super_large_net + large_net
    active_amount = sum(_flow_active_amount(record) for record in records)
    summary = {
        "symbol": symbol,
        "days": days,
        "records_used": len(records),
        **windows,
        "super_large_net_amount": super_large_net,
        "large_net_amount": large_net,
        "medium_net_amount": medium_net,
        "small_net_amount": small_net,
        "main_net_amount": main_net,
        "main_net_ratio": None if active_amount == 0 else round(main_net / active_amount, 6),
        "consecutive_flow_days": _consecutive_flow_days(records),
    }
    return {
        "ok": True,
        "source": "amstock",
        "function": "quote-flow-summary",
        "params": {"symbol": symbol, "days": days, "st": st, "et": et},
        "rows": 1,
        "returned_rows": 1,
        "columns": list(summary),
        "data": [summary],
        "raw_rows": raw.get("rows"),
    }


def _payload_records(payload: dict[str, object]) -> list[dict[str, object]]:
    data = payload.get("data")
    if isinstance(data, list):
        return [record for record in data if isinstance(record, dict)]
    if isinstance(data, dict):
        nested = data.get("data")
        if isinstance(nested, list):
            return [record for record in nested if isinstance(record, dict)]
    return []


def _recent_records(
    records: list[dict[str, object]],
    days: int,
) -> list[dict[str, object]]:
    with_time = [record for record in records if isinstance(record.get("t"), str)]
    if len(with_time) == len(records):
        records = sorted(records, key=lambda record: str(record.get("t")), reverse=True)
    return records[:days]


def _payload_row_count(payload: dict[str, object]) -> int:
    rows = payload.get("rows")
    if isinstance(rows, int):
        return rows
    return len(_payload_records(payload))


def _record_change_percent(record: dict[str, object]) -> float | None:
    for key in ("zf", "涨跌幅", "changePercent", "pctChg", "zdf", "pchg"):
        value = record.get(key)
        if isinstance(value, int | float):
            return float(value)
        if isinstance(value, str) and value.strip():
            try:
                return float(value.strip().strip("%"))
            except ValueError:
                continue
    return None


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    middle = len(values) // 2
    if len(values) % 2:
        return values[middle]
    return (values[middle - 1] + values[middle]) / 2


def _max_numeric_field(records: list[dict[str, object]], keys: tuple[str, ...]) -> float | None:
    values: list[float] = []
    for record in records:
        for key in keys:
            value = record.get(key)
            if isinstance(value, int | float):
                values.append(float(value))
                break
            if isinstance(value, str) and value.strip():
                try:
                    values.append(float(value))
                    break
                except ValueError:
                    continue
    return max(values) if values else None


def _window_main_net(records: list[dict[str, object]], size: int) -> float:
    return sum(_flow_main_net(record) for record in records[:size])


def _flow_main_net(record: dict[str, object]) -> float:
    return _flow_net(record, "td") + _flow_net(record, "dd")


def _flow_net(record: dict[str, object], bucket: str) -> float:
    return _number(record.get(f"zmb{bucket}cjzl")) - _number(record.get(f"zms{bucket}cjzl"))


def _flow_active_amount(record: dict[str, object]) -> float:
    buckets = ("td", "dd", "zd", "xd")
    buy = sum(_number(record.get(f"zmb{bucket}cjzl")) for bucket in buckets)
    sell = sum(_number(record.get(f"zms{bucket}cjzl")) for bucket in buckets)
    return buy + sell


def _consecutive_flow_days(records: list[dict[str, object]]) -> int:
    if not records:
        return 0
    first = _flow_main_net(records[0])
    if first == 0:
        return 0
    direction = 1 if first > 0 else -1
    count = 0
    for record in records:
        value = _flow_main_net(record)
        if value == 0 or (1 if value > 0 else -1) != direction:
            break
        count += direction
    return count


def _number(value: object) -> float:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value.strip().strip("%"))
        except ValueError:
            return 0.0
    return 0.0


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


def _akshare_dataframe(
    function: str,
    params: dict[str, object],
    *,
    limit: int | None,
    no_proxy: bool,
    ipv4: bool,
) -> dict[str, object]:
    """Run an AKShare DataFrame function and return the standard JSON payload."""

    configure_network(no_proxy=no_proxy, ipv4=ipv4)
    import akshare as ak

    dataframe = getattr(ak, function)(**params)
    return dataframe_payload(function, params, dataframe, limit=limit)


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
app.add_typer(config_app, name="config")
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
