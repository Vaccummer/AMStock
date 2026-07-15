"""Command-line entry point."""

from __future__ import annotations

import contextlib
import io
import json
import re
from typing import TYPE_CHECKING, Annotated, Literal

import typer

from amstock import __version__
from amstock.akshare_io import configure_network, dataframe_payload
from amstock.biying_io import DEFAULT_TIMEOUT_SECONDS, fetch_biying_dataset
from amstock.config import amstock_home, config_path, default_config_toml, resolve_config_path
from amstock.exceptions import AMStockError
from amstock.news_io import (
    DEFAULT_GDELT_BASE_URL,
    DEFAULT_MARKETAUX_BASE_URL,
    DEFAULT_NEWS_TIMEOUT_SECONDS,
    fetch_gdelt_news,
    fetch_marketaux_news,
)
from amstock.news_server import (
    flush_news_queue,
    load_news_server_config,
    news_list_payload,
    news_queue_payload,
    replay_news,
    run_news_once,
    run_news_server,
    subscriber_list_payload,
)
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
from amstock.twelvedata_io import (
    fetch_twelvedata_price,
    fetch_twelvedata_quote,
    fetch_twelvedata_quotes,
    fetch_twelvedata_symbol_search,
    fetch_twelvedata_time_series,
)

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
news_app = typer.Typer(no_args_is_help=True)
news_subscriber_app = typer.Typer(no_args_is_help=True)
us_app = typer.Typer(no_args_is_help=True)

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
NewsTokenOption = Annotated[str | None, typer.Option("--token", help="News API token.")]
NewsTimeoutOption = Annotated[float, typer.Option("--timeout", help="News API timeout in seconds.")]
TwelveDataApiKeyOption = Annotated[
    str | None,
    typer.Option("--api-key", help="Twelve Data API key."),
]
TwelveDataBaseUrlOption = Annotated[
    str | None,
    typer.Option("--base-url", help="Twelve Data API base URL."),
]
TwelveDataTimeoutOption = Annotated[
    float | None,
    typer.Option("--timeout", help="Twelve Data HTTP timeout in seconds."),
]
TwelveDataProxyOption = Annotated[
    str | None,
    typer.Option("--proxy-url", help="HTTP proxy URL for Twelve Data requests."),
]

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


@us_app.command("price")
def us_price(
    symbol: Annotated[str, typer.Option("--symbol", help="US stock symbol, e.g. NVDA.")],
    api_key: TwelveDataApiKeyOption = None,
    base_url: TwelveDataBaseUrlOption = None,
    timeout: TwelveDataTimeoutOption = None,
    proxy_url: TwelveDataProxyOption = None,
) -> None:
    """Fetch the latest US stock price through Twelve Data."""

    _run_json(
        lambda: fetch_twelvedata_price(
            symbol=symbol,
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            proxy_url=proxy_url,
        ),
    )


@us_app.command("quote")
def us_quote(
    symbol: Annotated[str, typer.Option("--symbol", help="US stock symbol, e.g. AAPL.")],
    api_key: TwelveDataApiKeyOption = None,
    base_url: TwelveDataBaseUrlOption = None,
    timeout: TwelveDataTimeoutOption = None,
    proxy_url: TwelveDataProxyOption = None,
) -> None:
    """Fetch a US stock quote snapshot through Twelve Data."""

    _run_json(
        lambda: fetch_twelvedata_quote(
            symbol=symbol,
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            proxy_url=proxy_url,
        ),
    )


@us_app.command("quotes")
def us_quotes(
    symbols: Annotated[
        str,
        typer.Option("--symbols", help="Comma-separated US symbols, e.g. AAPL,MSFT,NVDA."),
    ],
    api_key: TwelveDataApiKeyOption = None,
    base_url: TwelveDataBaseUrlOption = None,
    timeout: TwelveDataTimeoutOption = None,
    proxy_url: TwelveDataProxyOption = None,
) -> None:
    """Fetch multiple US stock quote snapshots through Twelve Data."""

    _run_json(
        lambda: fetch_twelvedata_quotes(
            symbols=symbols,
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            proxy_url=proxy_url,
        ),
    )


@us_app.command("history")
def us_history(
    symbol: Annotated[str, typer.Option("--symbol", help="US stock symbol, e.g. NVDA.")],
    interval: Annotated[
        str,
        typer.Option("--interval", help="Twelve Data interval, e.g. 1min, 5min, 1day."),
    ] = "1day",
    outputsize: Annotated[
        int | None,
        typer.Option("--outputsize", help="Number of bars to return."),
    ] = None,
    start_date: Annotated[
        str | None,
        typer.Option("--start-date", help="Start date/time accepted by Twelve Data."),
    ] = None,
    end_date: Annotated[
        str | None,
        typer.Option("--end-date", help="End date/time accepted by Twelve Data."),
    ] = None,
    api_key: TwelveDataApiKeyOption = None,
    base_url: TwelveDataBaseUrlOption = None,
    timeout: TwelveDataTimeoutOption = None,
    proxy_url: TwelveDataProxyOption = None,
) -> None:
    """Fetch US stock historical bars through Twelve Data."""

    _run_json(
        lambda: fetch_twelvedata_time_series(
            symbol=symbol,
            interval=interval,
            outputsize=outputsize,
            start_date=start_date,
            end_date=end_date,
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            proxy_url=proxy_url,
        ),
    )


@us_app.command("search")
def us_search(
    query: Annotated[str, typer.Option("--query", help="Symbol or company name to search.")],
    api_key: TwelveDataApiKeyOption = None,
    base_url: TwelveDataBaseUrlOption = None,
    timeout: TwelveDataTimeoutOption = None,
    proxy_url: TwelveDataProxyOption = None,
) -> None:
    """Search Twelve Data symbols."""

    _run_json(
        lambda: fetch_twelvedata_symbol_search(
            query=query,
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            proxy_url=proxy_url,
        ),
    )


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
    source: Annotated[
        Literal["auto", "biying", "sina"],
        typer.Option("--source", help="All-market quote source."),
    ] = "auto",
    licences: BiyingLicencesOption = None,
    base_url: BiyingBaseUrlOption = "https://api.biyingapi.com",
    timeout: BiyingTimeoutOption = DEFAULT_TIMEOUT_SECONDS,
    limit: LimitOption = None,
    no_proxy: NoProxyOption = False,
    ipv4: Ipv4Option = False,
) -> None:
    """Fetch all-market realtime stock quotes."""

    _run_json(
        lambda: _quote_all_payload(
            feed=feed,
            source=source,
            licences=licences,
            base_url=base_url,
            timeout=timeout,
            limit=limit,
            no_proxy=no_proxy,
            ipv4=ipv4,
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
    no_proxy: NoProxyOption = False,
    ipv4: Ipv4Option = False,
) -> None:
    """Calculate market breadth from all-market realtime quotes."""

    _run_json(
        lambda: _quote_breadth_payload(
            feed=feed,
            licences=licences,
            base_url=base_url,
            timeout=timeout,
            no_proxy=no_proxy,
            ipv4=ipv4,
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
    no_proxy: NoProxyOption = False,
    ipv4: Ipv4Option = False,
) -> None:
    """Calculate a market sentiment snapshot from stock pools and breadth."""

    _run_json(
        lambda: _sentiment_payload(
            date=date,
            feed=feed,
            licences=licences,
            base_url=base_url,
            timeout=timeout,
            no_proxy=no_proxy,
            ipv4=ipv4,
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
    source: Annotated[
        Literal["auto", "biying", "akshare"],
        typer.Option("--source", help="Quote source; auto falls back to AKShare if Biying fails."),
    ] = "auto",
    licences: BiyingLicencesOption = None,
    base_url: BiyingBaseUrlOption = "https://api.biyingapi.com",
    timeout: BiyingTimeoutOption = DEFAULT_TIMEOUT_SECONDS,
    limit: LimitOption = None,
    no_proxy: NoProxyOption = False,
    ipv4: Ipv4Option = False,
) -> None:
    """Fetch a realtime index quote."""

    _run_json(
        lambda: _index_quote_payload(
            index=index,
            source=source,
            licences=licences,
            base_url=base_url,
            timeout=timeout,
            limit=limit,
            no_proxy=no_proxy,
            ipv4=ipv4,
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
        Literal["sse", "szse"] | None,
        typer.Option("--exchange", help="Exchange to query."),
    ] = None,
    symbol: Annotated[
        str | None,
        typer.Option("--symbol", help="Optional ETF code to filter, e.g. 159995."),
    ] = None,
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

    resolved_exchange = exchange or (_infer_fund_exchange(symbol) if symbol else None)
    if resolved_exchange is None:
        raise typer.BadParameter("either --exchange or --symbol is required")

    if resolved_exchange == "sse":
        _run_json(
            lambda: _filter_symbol_payload(
                _akshare_dataframe(
                    "fund_etf_scale_sse",
                    {"date": date or ""},
                    limit=None if symbol else limit,
                    no_proxy=no_proxy,
                    ipv4=ipv4,
                ),
                symbol=symbol,
                limit=limit,
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
        lambda: _filter_symbol_payload(
            _akshare_dataframe(
                "fund_scale_daily_szse",
                params,
                limit=None if symbol else limit,
                no_proxy=no_proxy,
                ipv4=ipv4,
            ),
            symbol=symbol,
            limit=limit,
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


@news_app.command("gdelt")
def news_gdelt(
    endpoint: Annotated[
        Literal["stories", "events", "media-events"],
        typer.Option("--endpoint", help="GDELT Cloud endpoint to query."),
    ] = "stories",
    query: Annotated[
        str | None,
        typer.Option("--query", "--search", help="Keyword query for GDELT stories/events."),
    ] = None,
    start_date: Annotated[
        str | None,
        typer.Option("--start-date", "--from", help="Start date/time passed as date_start."),
    ] = None,
    end_date: Annotated[
        str | None,
        typer.Option("--end-date", "--to", help="End date/time passed as date_end."),
    ] = None,
    date: Annotated[
        str | None,
        typer.Option("--date", help="Date for media-events queries."),
    ] = None,
    days: Annotated[
        int | None,
        typer.Option("--days", help="Recent-day window for media-events queries."),
    ] = None,
    country: Annotated[
        str | None,
        typer.Option("--country", help="Country filter, e.g. US, CN, RU."),
    ] = None,
    language: Annotated[
        str | None,
        typer.Option("--language", help="Language filter when supported by the endpoint."),
    ] = None,
    domain: Annotated[
        str | None,
        typer.Option("--domain", help="Source domain filter when supported."),
    ] = None,
    category: Annotated[
        str | None,
        typer.Option("--category", help="GDELT category/topic filter when supported."),
    ] = None,
    sort: Annotated[
        str | None,
        typer.Option("--sort", help="Sort mode accepted by GDELT Cloud."),
    ] = None,
    limit: LimitOption = 20,
    token: NewsTokenOption = None,
    base_url: Annotated[
        str,
        typer.Option("--base-url", help="GDELT Cloud API base URL."),
    ] = DEFAULT_GDELT_BASE_URL,
    timeout: NewsTimeoutOption = DEFAULT_NEWS_TIMEOUT_SECONDS,
) -> None:
    """Fetch global political, military, policy, and macro news from GDELT Cloud."""

    _run_json(
        lambda: fetch_gdelt_news(
            endpoint=endpoint,
            params={
                "search": query,
                "date_start": start_date,
                "date_end": end_date,
                "date": date,
                "days": days,
                "country": country,
                "language": language,
                "domain": domain,
                "category": category,
                "sort": sort,
            },
            token_value=token,
            base_url=base_url,
            timeout=timeout,
            limit=limit,
        )
    )


@news_app.command("marketaux")
def news_marketaux(
    query: Annotated[
        str | None,
        typer.Option("--query", "--search", help="Full-text news search query."),
    ] = None,
    symbols: Annotated[
        str | None,
        typer.Option("--symbols", help="Comma-separated market symbols, e.g. AAPL,NVDA,SPY."),
    ] = None,
    countries: Annotated[
        str | None,
        typer.Option("--countries", help="Comma-separated country codes, e.g. us,cn."),
    ] = None,
    industries: Annotated[
        str | None,
        typer.Option("--industries", help="Comma-separated industries."),
    ] = None,
    language: Annotated[
        str | None,
        typer.Option("--language", help="News language, e.g. en."),
    ] = "en",
    published_after: Annotated[
        str | None,
        typer.Option("--published-after", "--from", help="Lower publication date/time bound."),
    ] = None,
    published_before: Annotated[
        str | None,
        typer.Option("--published-before", "--to", help="Upper publication date/time bound."),
    ] = None,
    filter_entities: Annotated[
        bool,
        typer.Option("--filter-entities/--no-filter-entities", help="Filter by detected entities."),
    ] = True,
    limit: LimitOption = 20,
    page: Annotated[int | None, typer.Option("--page", help="Marketaux page number.")] = None,
    token: NewsTokenOption = None,
    base_url: Annotated[
        str,
        typer.Option("--base-url", help="Marketaux API base URL."),
    ] = DEFAULT_MARKETAUX_BASE_URL,
    timeout: NewsTimeoutOption = DEFAULT_NEWS_TIMEOUT_SECONDS,
) -> None:
    """Fetch market and asset-linked financial news from Marketaux."""

    _run_json(
        lambda: fetch_marketaux_news(
            params={
                "search": query,
                "symbols": symbols,
                "countries": countries,
                "industries": industries,
                "language": language,
                "published_after": published_after,
                "published_before": published_before,
                "filter_entities": filter_entities,
                "page": page,
            },
            token_value=token,
            base_url=base_url,
            timeout=timeout,
            limit=limit,
        )
    )


@news_app.command("once")
def news_once() -> None:
    """Run one news collection, AstrBot review, and delivery cycle."""

    _run_json(lambda: run_news_once())


@news_app.command("server")
def news_server(
    max_cycles: Annotated[
        int | None,
        typer.Option("--max-cycles", help="Stop after this many cycles; useful for debugging."),
    ] = None,
) -> None:
    """Run the polling news server."""

    try:
        run_news_server(load_news_server_config(), max_cycles=max_cycles)
    except Exception as exc:
        _echo_json({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}})
        raise typer.Exit(1) from exc


@news_app.command("queue")
def news_queue(limit: LimitOption = 50) -> None:
    """Show queued news deliveries waiting for quiet hours to end."""

    _run_json(lambda: news_queue_payload(limit=limit or 50))


@news_app.command("list")
def news_list(
    limit: LimitOption = 50,
    source: Annotated[str, typer.Option("--source", help="Filter by configured source name.")] = "",
    provider: Annotated[
        str,
        typer.Option("--provider", help="Filter by normalized provider."),
    ] = "",
    query: Annotated[
        str,
        typer.Option("--query", "--search", help="Search title, summary, and raw JSON."),
    ] = "",
    since: Annotated[
        str,
        typer.Option("--since", help="Filter first_seen_at or published_at at/after this value."),
    ] = "",
    subscriber: Annotated[
        str,
        typer.Option("--subscriber", help="Use this subscriber for review/delivery filters."),
    ] = "",
    delivery_status: Annotated[
        str,
        typer.Option(
            "--delivery-status",
            help="Filter by delivery status, e.g. sent/queued/failed.",
        ),
    ] = "",
    review_push: Annotated[
        str,
        typer.Option("--review-push", help="Filter reviewed push decision: true or false."),
    ] = "",
) -> None:
    """List stored news items matching read-only filters."""

    _run_json(
        lambda: news_list_payload(
            limit=limit or 50,
            source=source,
            provider=provider,
            query=query,
            since=since,
            subscriber_name=subscriber,
            delivery_status=delivery_status,
            review_push=review_push,
        )
    )


@news_app.command("flush")
def news_flush() -> None:
    """Send queued news deliveries if quiet hours are over."""

    _run_json(lambda: flush_news_queue())


@news_app.command("replay")
def news_replay(
    limit: LimitOption = 50,
    since: Annotated[
        str,
        typer.Option(
            "--since",
            help="Replay news first seen or published at/after this text value.",
        ),
    ] = "",
    subscriber: Annotated[
        str,
        typer.Option("--subscriber", help="Only replay for this subscriber name."),
    ] = "",
    include_sent: Annotated[
        bool,
        typer.Option("--include-sent", help="Allow replaying items already marked sent."),
    ] = False,
) -> None:
    """Replay stored news through AstrBot review and delivery."""

    _run_json(
        lambda: replay_news(
            limit=limit or 50,
            since=since,
            subscriber_name=subscriber,
            include_sent=include_sent,
        )
    )


@news_subscriber_app.command("list")
def news_subscriber_list() -> None:
    """List configured news subscribers."""

    _run_json(lambda: subscriber_list_payload())


@news_subscriber_app.command("add")
def news_subscriber_add(
    name: Annotated[str, typer.Option("--name", help="Subscriber name.")],
    umo: Annotated[str, typer.Option("--umo", help="AstrBot unified message origin.")],
    sources: Annotated[
        str,
        typer.Option("--sources", help="Comma-separated accepted source names."),
    ] = "",
    min_importance: Annotated[
        int,
        typer.Option("--min-importance", help="Minimum review importance to push."),
    ] = 4,
    enabled: Annotated[
        bool,
        typer.Option("--enabled/--disabled", help="Create subscriber enabled or disabled."),
    ] = True,
    prompt_prefix: Annotated[
        str,
        typer.Option("--prompt-prefix", help="Subscriber-specific review preference."),
    ] = "",
    prompt_suffix: Annotated[
        str,
        typer.Option("--prompt-suffix", help="Subscriber-specific final output preference."),
    ] = "",
    news_preference: Annotated[
        str,
        typer.Option("--news-preference", help="Natural-language news rating preference."),
    ] = "",
    min_keep_importance: Annotated[
        int,
        typer.Option("--min-keep-importance", help="Minimum importance to keep in cache."),
    ] = 2,
    realtime_min_importance: Annotated[
        int,
        typer.Option("--realtime-min-importance", help="Minimum importance for realtime push."),
    ] = 5,
    realtime_min_urgency: Annotated[
        int,
        typer.Option("--realtime-min-urgency", help="Minimum urgency for realtime push."),
    ] = 4,
    rating_batch_size: Annotated[
        int,
        typer.Option("--rating-batch-size", help="News items per rating-agent batch."),
    ] = 30,
    digest_min_items: Annotated[
        int,
        typer.Option("--digest-min-items", help="Minimum cached items before digest push."),
    ] = 10,
    digest_max_items: Annotated[
        int,
        typer.Option("--digest-max-items", help="Maximum cached items per digest push."),
    ] = 40,
    digest_times: Annotated[
        str,
        typer.Option("--digest-times", help="Comma-separated HH:MM digest push times."),
    ] = "10:00,12:00,15:10,20:30",
    review_session_id: Annotated[
        str,
        typer.Option("--review-session-id", help="Dedicated AstrBot review session id."),
    ] = "",
    max_context_chars: Annotated[
        int,
        typer.Option("--max-context-chars", help="Maximum chars before batch summarization."),
    ] = 12000,
    quiet_start: Annotated[
        str,
        typer.Option("--quiet-start", help="Quiet-hours start HH:MM."),
    ] = "23:00",
    quiet_end: Annotated[str, typer.Option("--quiet-end", help="Quiet-hours end HH:MM.")] = "08:30",
) -> None:
    """Add a news subscriber to the config file."""

    _run_json(
        lambda: add_news_subscriber_config(
            name=name,
            umo=umo,
            sources=sources,
            min_importance=min_importance,
            enabled=enabled,
            prompt_prefix=prompt_prefix,
            prompt_suffix=prompt_suffix,
            news_preference=news_preference,
            min_keep_importance=min_keep_importance,
            realtime_min_importance=realtime_min_importance,
            realtime_min_urgency=realtime_min_urgency,
            rating_batch_size=rating_batch_size,
            digest_min_items=digest_min_items,
            digest_max_items=digest_max_items,
            digest_times=digest_times,
            review_session_id=review_session_id,
            max_context_chars=max_context_chars,
            quiet_start=quiet_start,
            quiet_end=quiet_end,
        )
    )


@news_subscriber_app.command("pause")
def news_subscriber_pause(name: Annotated[str, typer.Argument(help="Subscriber name.")]) -> None:
    """Pause a news subscriber."""

    _run_json(lambda: set_news_subscriber_enabled(name, False))


@news_subscriber_app.command("resume")
def news_subscriber_resume(name: Annotated[str, typer.Argument(help="Subscriber name.")]) -> None:
    """Resume a news subscriber."""

    _run_json(lambda: set_news_subscriber_enabled(name, True))


@news_subscriber_app.command("sources")
def news_subscriber_sources(
    name: Annotated[str, typer.Argument(help="Subscriber name.")],
    sources: Annotated[str, typer.Option("--set", help="Comma-separated source names.")],
) -> None:
    """Replace a subscriber's accepted source list."""

    _run_json(lambda: set_news_subscriber_sources(name, sources))


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


def _quote_all_payload(
    *,
    feed: str,
    source: str,
    licences: str | None,
    base_url: str,
    timeout: float,
    limit: int | None,
    no_proxy: bool,
    ipv4: bool,
) -> dict[str, object]:
    if source in {"auto", "biying"}:
        try:
            return _fetch_quote_all(
                feed=feed,
                licences=licences,
                base_url=base_url,
                timeout=timeout,
                limit=limit,
            )
        except Exception as exc:
            if source == "biying":
                raise
            payload = _akshare_sina_spot_payload(
                limit=limit,
                no_proxy=no_proxy,
                ipv4=ipv4,
            )
            payload["fallback_from"] = {
                "source": "biying",
                "function": f"stock-all-{feed}",
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }
            return payload

    return _akshare_sina_spot_payload(limit=limit, no_proxy=no_proxy, ipv4=ipv4)


def _quote_breadth_payload(
    *,
    feed: str,
    licences: str | None,
    base_url: str,
    timeout: float,
    no_proxy: bool,
    ipv4: bool,
) -> dict[str, object]:
    try:
        return _breadth_payload(
            _fetch_quote_all(
                feed=feed,
                licences=licences,
                base_url=base_url,
                timeout=timeout,
                limit=None,
            )
        )
    except Exception as exc:
        payload = _breadth_payload(
            _akshare_breadth_source_payload(no_proxy=no_proxy, ipv4=ipv4)
        )
        payload["fallback_from"] = {
            "source": "biying",
            "function": f"stock-all-{feed}",
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }
        return payload


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
    no_proxy: bool,
    ipv4: bool,
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
    breadth = _quote_breadth_payload(
        feed=feed,
        licences=licences,
        base_url=base_url,
        timeout=timeout,
        no_proxy=no_proxy,
        ipv4=ipv4,
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
        "fallback_from": breadth.get("fallback_from"),
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


def _akshare_sina_spot_payload(
    *,
    limit: int | None,
    no_proxy: bool,
    ipv4: bool,
) -> dict[str, object]:
    return _akshare_dataframe(
        "stock_zh_a_spot",
        {},
        limit=limit,
        no_proxy=no_proxy,
        ipv4=ipv4,
    )


def _akshare_breadth_source_payload(*, no_proxy: bool, ipv4: bool) -> dict[str, object]:
    return _akshare_sina_spot_payload(limit=None, no_proxy=no_proxy, ipv4=ipv4)


def _index_quote_payload(
    *,
    index: str,
    source: str,
    licences: str | None,
    base_url: str,
    timeout: float,
    limit: int | None,
    no_proxy: bool,
    ipv4: bool,
) -> dict[str, object]:
    if source in {"auto", "biying"}:
        try:
            return _fetch_biying(
                "index-realtime",
                {"index": index},
                licences=licences,
                base_url=base_url,
                timeout=timeout,
                limit=limit,
            )
        except Exception as exc:
            if source == "biying":
                raise
            payload = _akshare_index_quote_payload(
                index=index,
                limit=limit,
                no_proxy=no_proxy,
                ipv4=ipv4,
            )
            payload["fallback_from"] = {
                "source": "biying",
                "function": "index-realtime",
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }
            return payload

    return _akshare_index_quote_payload(
        index=index,
        limit=limit,
        no_proxy=no_proxy,
        ipv4=ipv4,
    )


def _akshare_index_quote_payload(
    *,
    index: str,
    limit: int | None,
    no_proxy: bool,
    ipv4: bool,
) -> dict[str, object]:
    normalized = _normalize_six_digit_symbol(index)
    attempts = [
        ("stock_zh_index_spot_em", {"symbol": _akshare_index_family(index)}),
        ("stock_zh_index_spot_sina", {}),
    ]
    first_error: Exception | None = None
    for function, params in attempts:
        try:
            payload = _akshare_dataframe(
                function,
                params,
                limit=None,
                no_proxy=no_proxy,
                ipv4=ipv4,
            )
        except Exception as exc:
            first_error = first_error or exc
            continue
        filtered = _filter_payload_records(
            payload,
            lambda record: _record_matches_symbol(record, normalized),
            symbol=normalized,
            limit=limit,
        )
        if filtered.get("rows") or function == attempts[-1][0]:
            if first_error is not None:
                filtered["akshare_fallback_from"] = {
                    "function": attempts[0][0],
                    "error": {
                        "type": type(first_error).__name__,
                        "message": str(first_error),
                    },
                }
            return filtered

    if first_error is not None:
        raise first_error
    raise ValueError(f"index quote not found for {index!r}")


def _filter_symbol_payload(
    payload: dict[str, object],
    *,
    symbol: str | None,
    limit: int | None,
) -> dict[str, object]:
    if not symbol:
        return payload
    normalized = _normalize_six_digit_symbol(symbol)
    return _filter_payload_records(
        payload,
        lambda record: _record_matches_symbol(record, normalized),
        symbol=normalized,
        limit=limit,
    )


def _filter_payload_records(
    payload: dict[str, object],
    predicate: Callable[[dict[str, object]], bool],
    *,
    symbol: str,
    limit: int | None,
) -> dict[str, object]:
    records = [record for record in _payload_records(payload) if predicate(record)]
    limited = records[:limit] if limit is not None else records
    filtered = dict(payload)
    params = filtered.get("params")
    if isinstance(params, dict):
        filtered["params"] = {**params, "filter_symbol": symbol}
    else:
        filtered["params"] = {"filter_symbol": symbol}
    filtered["rows"] = len(records)
    filtered["returned_rows"] = len(limited)
    filtered["data"] = limited
    return filtered


def _record_matches_symbol(record: dict[str, object], symbol: str) -> bool:
    for key in (
        "代码",
        "基金代码",
        "证券代码",
        "指数代码",
        "code",
        "fund_code",
        "symbol",
        "dm",
    ):
        value = record.get(key)
        if value is not None and _normalize_six_digit_symbol(str(value)) == symbol:
            return True
    return False


def _normalize_six_digit_symbol(symbol: str) -> str:
    text = symbol.strip().upper()
    if "." in text:
        text = text.split(".", 1)[0]
    for prefix in ("SH", "SZ", "BJ"):
        text = text.removeprefix(prefix)
    digits = "".join(char for char in text if char.isdigit())
    return digits[-6:] if len(digits) >= 6 else digits


def _infer_fund_exchange(symbol: str | None) -> str:
    normalized = _normalize_six_digit_symbol(symbol or "")
    if normalized.startswith(("51", "56", "58")):
        return "sse"
    if normalized.startswith(("15", "16", "18")):
        return "szse"
    msg = f"cannot infer exchange for fund symbol {symbol!r}; pass --exchange"
    raise ValueError(msg)


def _akshare_index_family(index: str) -> str:
    normalized = index.upper()
    code = _normalize_six_digit_symbol(index)
    if normalized.endswith(".SZ") or code.startswith(("399", "980")):
        return "深证系列指数"
    if normalized.endswith(".SH") or code.startswith(("000", "880")):
        return "上证系列指数"
    return "沪深重要指数"


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

    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        dataframe = getattr(ak, function)(**params)
    return dataframe_payload(function, params, dataframe, limit=limit)


def _biying_period(period: str) -> str:
    return {"daily": "d", "weekly": "w", "monthly": "m"}.get(period, period)


def _biying_adjust(adjust: str) -> str:
    return {"none": "n", "qfq": "q", "hfq": "h"}.get(adjust, adjust)


def _raise_value_error(message: str) -> dict[str, object]:
    raise ValueError(message)


def add_news_subscriber_config(
    *,
    name: str,
    umo: str,
    sources: str,
    min_importance: int,
    enabled: bool,
    prompt_prefix: str,
    prompt_suffix: str,
    news_preference: str,
    min_keep_importance: int,
    realtime_min_importance: int,
    realtime_min_urgency: int,
    rating_batch_size: int,
    digest_min_items: int,
    digest_max_items: int,
    digest_times: str,
    review_session_id: str,
    max_context_chars: int,
    quiet_start: str,
    quiet_end: str,
) -> dict[str, object]:
    """Append a news subscriber to AMSTOCK_HOME config."""

    if not name.strip():
        raise ValueError("subscriber name is required")
    if not umo.strip():
        raise ValueError("subscriber umo is required")
    path = resolve_config_path(amstock_home())
    lines = _read_config_lines()
    if _find_subscriber_block(lines, name.strip()) is not None:
        raise ValueError(f"news subscriber already exists: {name}")
    source_values = _split_csv(sources)
    digest_time_values = _split_csv(digest_times)
    preference = news_preference.strip() or prompt_prefix.strip()
    session_id = review_session_id.strip() or f"amstock-news-review-{_slug(name)}"
    block = [
        "",
        "[[astrbot.subscribers]]",
        f'name = {_toml_string(name.strip())}',
        f"enabled = {_toml_bool(enabled)}",
        f"umo = {_toml_string(umo.strip())}",
        f"min_importance = {min_importance}",
        "markets = []",
        f"sources = {_toml_string_list(source_values)}",
        f"prompt_prefix = {_toml_string(prompt_prefix.strip())}",
        f"prompt_suffix = {_toml_string(prompt_suffix.strip())}",
        f"news_preference = {_toml_string(preference)}",
        f"min_keep_importance = {min_keep_importance}",
        f"realtime_min_importance = {realtime_min_importance}",
        f"realtime_min_urgency = {realtime_min_urgency}",
        f"rating_batch_size = {rating_batch_size}",
        f"digest_min_items = {digest_min_items}",
        f"digest_max_items = {digest_max_items}",
        f"digest_times = {_toml_string_list(digest_time_values)}",
        f"review_session_id = {_toml_string(session_id)}",
        f"max_context_chars = {max_context_chars}",
        "",
        "[astrbot.subscribers.quiet_hours]",
        "enabled = true",
        f"start = {_toml_string(quiet_start)}",
        f"end = {_toml_string(quiet_end)}",
        "flush_on_end = true",
        "",
    ]
    lines.extend(block)
    _write_config_lines(lines)
    return {
        "ok": True,
        "function": "news-subscriber-add",
        "config_path": str(path),
        "name": name.strip(),
        "enabled": enabled,
        "sources": source_values,
        "news_preference": preference,
        "realtime_min_importance": realtime_min_importance,
        "realtime_min_urgency": realtime_min_urgency,
        "digest_min_items": digest_min_items,
        "digest_times": digest_time_values,
        "review_session_id": session_id,
    }


def set_news_subscriber_enabled(name: str, enabled: bool) -> dict[str, object]:
    """Set a news subscriber's enabled flag."""

    path = resolve_config_path(amstock_home())
    lines = _read_config_lines()
    block = _find_subscriber_block(lines, name)
    if block is None:
        raise ValueError(f"news subscriber not found: {name}")
    _set_key_in_block(lines, block[0], block[1], "enabled", _toml_bool(enabled))
    _write_config_lines(lines)
    return {
        "ok": True,
        "function": "news-subscriber-enabled",
        "config_path": str(path),
        "name": name,
        "enabled": enabled,
    }


def set_news_subscriber_sources(name: str, sources: str) -> dict[str, object]:
    """Replace a news subscriber's accepted sources."""

    path = resolve_config_path(amstock_home())
    source_values = _split_csv(sources)
    lines = _read_config_lines()
    block = _find_subscriber_block(lines, name)
    if block is None:
        raise ValueError(f"news subscriber not found: {name}")
    _set_key_in_block(lines, block[0], block[1], "sources", _toml_string_list(source_values))
    _write_config_lines(lines)
    return {
        "ok": True,
        "function": "news-subscriber-sources",
        "config_path": str(path),
        "name": name,
        "sources": source_values,
    }


def _read_config_lines() -> list[str]:
    path = resolve_config_path(amstock_home())
    return path.read_text(encoding="utf-8").splitlines()


def _write_config_lines(lines: list[str]) -> None:
    path = resolve_config_path(amstock_home())
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _find_subscriber_block(lines: list[str], name: str) -> tuple[int, int] | None:
    for start, end in _subscriber_blocks(lines):
        block_text = "\n".join(lines[start:end])
        match = re.search(r'(?m)^name\s*=\s*"([^"]+)"\s*$', block_text)
        if match and match.group(1) == name:
            return start, end
    return None


def _subscriber_blocks(lines: list[str]) -> list[tuple[int, int]]:
    starts = [
        index for index, line in enumerate(lines) if line.strip() == "[[astrbot.subscribers]]"
    ]
    blocks: list[tuple[int, int]] = []
    for position, start in enumerate(starts):
        next_start = starts[position + 1] if position + 1 < len(starts) else len(lines)
        end = next_start
        for index in range(start + 1, next_start):
            stripped = lines[index].strip()
            if stripped.startswith("[") and not stripped.startswith("[astrbot.subscribers"):
                end = index
                break
        blocks.append((start, end))
    return blocks


def _set_key_in_block(lines: list[str], start: int, end: int, key: str, value: str) -> None:
    pattern = re.compile(rf"^{re.escape(key)}\s*=")
    insert_at = end
    for index in range(start + 1, end):
        stripped = lines[index].strip()
        if stripped.startswith("[astrbot.subscribers."):
            insert_at = index
            break
        if pattern.match(stripped):
            lines[index] = f"{key} = {value}"
            return
    lines.insert(insert_at, f"{key} = {value}")


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _toml_bool(value: bool) -> str:
    return "true" if value else "false"


def _toml_string_list(values: list[str]) -> str:
    return "[" + ", ".join(_toml_string(value) for value in values) + "]"


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-") or "subscriber"


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
app.add_typer(us_app, name="us")
news_app.add_typer(news_subscriber_app, name="subscriber")
app.add_typer(news_app, name="news")
app.add_typer(sources_app, name="sources")
app.add_typer(portfolio_app, name="portfolio")


def main() -> None:
    """Run the command-line application."""

    app()
