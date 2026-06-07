"""Query functions for the agent-facing AMStock source CLI."""

from __future__ import annotations

from datetime import datetime

from amstock.akshare_io import (
    configure_network,
    dataframe_payload,
    normalize_a_stock_code,
    sina_stock_code,
)
from amstock.baostock_io import baostock_session, normalize_baostock_code, result_set_payload
from amstock.biying_io import BIYING_ENDPOINTS

ADJUST_MAP = {
    "none": "",
    "qfq": "qfq",
    "hfq": "hfq",
}
BAOSTOCK_ADJUST_MAP = {
    "none": "3",
    "qfq": "2",
    "hfq": "1",
}
BAOSTOCK_PERIOD_MAP = {
    "daily": "d",
    "weekly": "w",
    "monthly": "m",
}
BAOSTOCK_HISTORY_FIELDS = "date,code,open,high,low,close,volume,amount,turn,pctChg"
REPORT_TYPE_MAP = {
    "balance": "资产负债表",
    "cash-flow": "现金流量表",
    "income": "利润表",
}


def capabilities_payload() -> dict[str, object]:
    """Return machine-readable CLI capabilities."""

    return {
        "ok": True,
        "cli": "amstock_src",
        "purpose": "query China A-share source data for agents",
        "commands": [
            {
                "name": "a-spot",
                "description": "Fetch all A-share spot/basic trading list data.",
                "source": "baostock",
                "notes": ["Use --date to query a specific trading day."],
            },
            {
                "name": "stock-basic",
                "description": "Fetch one A-share's basic company/listing information.",
                "required": ["--symbol"],
                "source": "baostock",
            },
            {
                "name": "price-history",
                "description": "Fetch A-share daily/weekly/monthly historical K-line data.",
                "required": ["--symbol"],
                "options": ["--period daily|weekly|monthly", "--adjust none|qfq|hfq"],
                "source": "baostock",
            },
            {
                "name": "exchange-summary",
                "description": "Fetch SSE or SZSE market summary data.",
                "required": ["--exchange sse|szse"],
                "source": "akshare",
            },
            {
                "name": "financial-abstract",
                "description": "Fetch A-share financial abstract data.",
                "required": ["--symbol"],
                "source": "akshare",
            },
            {
                "name": "financial-report",
                "description": "Fetch balance sheet, income statement, or cash-flow statement.",
                "required": ["--symbol", "--report-type balance|income|cash-flow"],
                "source": "akshare",
            },
            {
                "name": "industry-list",
                "description": (
                    "Fetch BaoStock industry classification data. This is not the same as "
                    "Eastmoney board rankings."
                ),
                "source": "baostock",
            },
            {
                "name": "biying",
                "description": (
                    "Fetch high-value A-share/BJ/STAR/index/fund datasets through Biying API."
                ),
                "required": [
                    "--dataset",
                    "--licences, AMSTOCK_BIYING_LICENCES, or configured Biying credentials",
                ],
                "source": "biying",
                "datasets": sorted(BIYING_ENDPOINTS),
            },
        ],
        "common_options": ["--limit", "--no-proxy", "--ipv4"],
        "output": "single JSON object on stdout; failed commands also emit JSON and exit non-zero",
        "routing": "fixed per command; no runtime fallback",
        "unsupported_now": ["concept-list", "concept-cons", "industry-cons"],
    }


def fetch_a_spot(
    *,
    date: str | None = None,
    limit: int | None = None,
    no_proxy: bool = False,
    ipv4: bool = False,
) -> dict[str, object]:
    """Fetch all A-share spot/basic trading list data from BaoStock."""

    _configure_baostock_compatible_network(no_proxy=no_proxy, ipv4=ipv4)
    return _baostock_all_stock(date=date, limit=limit)


def fetch_stock_basic(
    *,
    symbol: str,
    limit: int | None = None,
    no_proxy: bool = False,
    ipv4: bool = False,
) -> dict[str, object]:
    """Fetch basic information for one A-share from BaoStock."""

    _configure_baostock_compatible_network(no_proxy=no_proxy, ipv4=ipv4)
    return _baostock_stock_basic(symbol=symbol, limit=limit)


def fetch_price_history(
    *,
    symbol: str,
    period: str = "daily",
    start_date: str = "19700101",
    end_date: str = "20500101",
    adjust: str = "none",
    limit: int | None = None,
    no_proxy: bool = False,
    ipv4: bool = False,
) -> dict[str, object]:
    """Fetch historical A-share K-line data from BaoStock."""

    _configure_baostock_compatible_network(no_proxy=no_proxy, ipv4=ipv4)
    return _baostock_price_history(
        symbol=symbol,
        period=period,
        start_date=start_date,
        end_date=end_date,
        adjust=adjust,
        limit=limit,
    )


def fetch_exchange_summary(
    *,
    exchange: str,
    date: str | None = None,
    limit: int | None = None,
    no_proxy: bool = False,
    ipv4: bool = False,
) -> dict[str, object]:
    """Fetch Shanghai or Shenzhen exchange summary data."""

    configure_network(no_proxy=no_proxy, ipv4=ipv4)
    import akshare as ak

    if exchange == "sse":
        dataframe = ak.stock_sse_summary()
        return dataframe_payload("stock_sse_summary", {}, dataframe, limit=limit)

    params = {}
    if date:
        params["date"] = date
    dataframe = ak.stock_szse_summary(**params)
    return dataframe_payload("stock_szse_summary", params, dataframe, limit=limit)


def fetch_financial_abstract(
    *,
    symbol: str,
    limit: int | None = None,
    no_proxy: bool = False,
    ipv4: bool = False,
) -> dict[str, object]:
    """Fetch financial abstract data from AKShare."""

    configure_network(no_proxy=no_proxy, ipv4=ipv4)
    import akshare as ak

    normalized = normalize_a_stock_code(symbol)
    dataframe = ak.stock_financial_abstract(normalized)
    return dataframe_payload(
        "stock_financial_abstract",
        {"symbol": normalized},
        dataframe,
        limit=limit,
    )


def fetch_financial_report(
    *,
    symbol: str,
    report_type: str,
    limit: int | None = None,
    no_proxy: bool = False,
    ipv4: bool = False,
) -> dict[str, object]:
    """Fetch a financial statement from AKShare."""

    configure_network(no_proxy=no_proxy, ipv4=ipv4)
    import akshare as ak

    params = {"stock": sina_stock_code(symbol), "symbol": REPORT_TYPE_MAP[report_type]}
    dataframe = ak.stock_financial_report_sina(**params)
    return dataframe_payload("stock_financial_report_sina", params, dataframe, limit=limit)


def fetch_industry_list(
    *,
    limit: int | None = None,
    no_proxy: bool = False,
    ipv4: bool = False,
) -> dict[str, object]:
    """Fetch industry classification data from BaoStock."""

    _configure_baostock_compatible_network(no_proxy=no_proxy, ipv4=ipv4)
    return _baostock_industry_list(limit=limit)


def _baostock_all_stock(*, date: str | None, limit: int | None) -> dict[str, object]:
    params = {"day": _baostock_day(date)}
    with baostock_session() as bs:
        return result_set_payload(
            "query_all_stock",
            params,
            bs.query_all_stock(**params),
            limit=limit,
        )


def _baostock_stock_basic(*, symbol: str, limit: int | None) -> dict[str, object]:
    params = {"code": normalize_baostock_code(symbol)}
    with baostock_session() as bs:
        return result_set_payload(
            "query_stock_basic",
            params,
            bs.query_stock_basic(**params),
            limit=limit,
        )


def _baostock_price_history(
    *,
    symbol: str,
    period: str,
    start_date: str,
    end_date: str,
    adjust: str,
    limit: int | None,
) -> dict[str, object]:
    params = {
        "code": normalize_baostock_code(symbol),
        "fields": BAOSTOCK_HISTORY_FIELDS,
        "start_date": _baostock_date(start_date),
        "end_date": _baostock_date(end_date),
        "frequency": BAOSTOCK_PERIOD_MAP[period],
        "adjustflag": BAOSTOCK_ADJUST_MAP[adjust],
    }
    with baostock_session() as bs:
        return result_set_payload(
            "query_history_k_data_plus",
            params,
            bs.query_history_k_data_plus(**params),
            limit=limit,
        )


def _baostock_industry_list(*, limit: int | None) -> dict[str, object]:
    params = {"code": "", "date": ""}
    with baostock_session() as bs:
        return result_set_payload(
            "query_stock_industry",
            params,
            bs.query_stock_industry(**params),
            limit=limit,
        )


def _baostock_day(value: str | None) -> str | None:
    if not value:
        return None
    if "-" in value:
        return value
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}"


def _baostock_date(value: str) -> str:
    if "-" in value:
        return value
    return datetime.strptime(value, "%Y%m%d").strftime("%Y-%m-%d")


def _configure_baostock_compatible_network(*, no_proxy: bool, ipv4: bool) -> None:
    """Apply shared network options for direct BaoStock queries."""

    configure_network(no_proxy=no_proxy, ipv4=ipv4)
