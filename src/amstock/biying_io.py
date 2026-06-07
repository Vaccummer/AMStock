"""Biying API helpers for high-value AMStock source datasets."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from amstock.akshare_io import normalize_a_stock_code
from amstock.config import amstock_home, load_settings
from amstock.exceptions import ConfigurationError

DEFAULT_BIYING_BASE_URL = "https://api.biyingapi.com"
BIYING_LICENCE_ENV = "AMSTOCK_BIYING_LICENCES"
BIYING_LEGACY_LICENCE_ENV = "AMSTOCK_BIYING_LICENCE"
BIYING_ROTATION_FILE_ENV = "AMSTOCK_BIYING_ROTATION_FILE"
DEFAULT_TIMEOUT_SECONDS = 20.0
RETRYABLE_HTTP_STATUS = {401, 403, 429, 500, 502, 503, 504}
JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]


@dataclass(frozen=True, slots=True)
class BiyingEndpoint:
    """Static metadata for one Biying API endpoint."""

    path: str
    description: str
    required: tuple[str, ...] = ()
    query: tuple[str, ...] = ()
    base_url: str | None = None


BIYING_ENDPOINTS: dict[str, BiyingEndpoint] = {
    # Lists, sectors, and theme relationships.
    "stock-list": BiyingEndpoint("/hslt/list/{licence}", "A-share stock list"),
    "ipo-calendar": BiyingEndpoint("/hslt/new/{licence}", "new stock calendar"),
    "sector-list": BiyingEndpoint("/hslt/sectorslist/{licence}", "broker concept sector list"),
    "primary-sector-list": BiyingEndpoint(
        "/hslt/primarylist/{licence}",
        "broker primary market sector list",
    ),
    "sector-detail": BiyingEndpoint(
        "/hslt/sectors/{sector}/{licence}",
        "stocks in a broker sector",
        required=("sector",),
    ),
    "concept-tree": BiyingEndpoint("/hszg/list/{licence}", "index, industry, concept tree"),
    "concept-stocks": BiyingEndpoint(
        "/hszg/gg/{code}/{licence}",
        "stocks for one index, industry, or concept code",
        required=("code",),
    ),
    "stock-concepts": BiyingEndpoint(
        "/hszg/zg/{symbol}/{licence}",
        "index, industry, and concepts for one stock",
        required=("symbol",),
    ),
    # Event pools.
    "limit-up-pool": BiyingEndpoint(
        "/hslt/ztgc/{date}/{licence}",
        "limit-up stock pool for a trading date",
        required=("date",),
    ),
    "limit-down-pool": BiyingEndpoint(
        "/hslt/dtgc/{date}/{licence}",
        "limit-down stock pool for a trading date",
        required=("date",),
    ),
    "strong-pool": BiyingEndpoint(
        "/hslt/qsgc/{date}/{licence}",
        "strong stock pool for a trading date",
        required=("date",),
    ),
    "new-stock-pool": BiyingEndpoint(
        "/hslt/cxgc/{date}/{licence}",
        "recently listed stock pool for a trading date",
        required=("date",),
    ),
    "limit-break-pool": BiyingEndpoint(
        "/hslt/zbgc/{date}/{licence}",
        "limit-board break stock pool for a trading date",
        required=("date",),
    ),
    # Company actions and holders.
    "company-profile": BiyingEndpoint(
        "/hscp/gsjj/{symbol}/{licence}",
        "company profile",
        required=("symbol",),
    ),
    "stock-indexes": BiyingEndpoint(
        "/hscp/sszs/{symbol}/{licence}",
        "indexes for one stock",
        required=("symbol",),
    ),
    "management": BiyingEndpoint(
        "/hscp/ljgg/{symbol}/{licence}",
        "historical senior management members",
        required=("symbol",),
    ),
    "directors": BiyingEndpoint(
        "/hscp/ljds/{symbol}/{licence}",
        "historical board members",
        required=("symbol",),
    ),
    "supervisors": BiyingEndpoint(
        "/hscp/ljjj/{symbol}/{licence}",
        "historical supervisory board members",
        required=("symbol",),
    ),
    "dividend": BiyingEndpoint(
        "/hscp/jnfh/{symbol}/{licence}",
        "recent dividends",
        required=("symbol",),
    ),
    "secondary-offering": BiyingEndpoint(
        "/hscp/jnzf/{symbol}/{licence}",
        "recent secondary offerings",
        required=("symbol",),
    ),
    "unlock": BiyingEndpoint(
        "/hscp/jjxs/{symbol}/{licence}",
        "restricted-share unlocks",
        required=("symbol",),
    ),
    "quarterly-profit": BiyingEndpoint(
        "/hscp/jdlr/{symbol}/{licence}",
        "recent quarterly profit data",
        required=("symbol",),
    ),
    "quarterly-cashflow": BiyingEndpoint(
        "/hscp/jdxj/{symbol}/{licence}",
        "recent quarterly cash-flow data",
        required=("symbol",),
    ),
    "performance-forecast": BiyingEndpoint(
        "/hscp/yjyg/{symbol}/{licence}",
        "earnings forecasts",
        required=("symbol",),
    ),
    "financial-indicator-summary": BiyingEndpoint(
        "/hscp/cwzb/{symbol}/{licence}",
        "financial indicator summary",
        required=("symbol",),
    ),
    "top-shareholders": BiyingEndpoint(
        "/hscp/sdgd/{symbol}/{licence}",
        "top ten shareholders",
        required=("symbol",),
    ),
    "top-float-shareholders": BiyingEndpoint(
        "/hscp/ltgd/{symbol}/{licence}",
        "top ten float shareholders",
        required=("symbol",),
    ),
    "shareholder-trend": BiyingEndpoint(
        "/hscp/gdbh/{symbol}/{licence}",
        "shareholder count trend",
        required=("symbol",),
    ),
    "fund-holding": BiyingEndpoint(
        "/hscp/jjcg/{symbol}/{licence}",
        "fund holdings for one stock",
        required=("symbol",),
    ),
    # Quotes, ticks, order book, money flow, and history.
    "stock-realtime-public": BiyingEndpoint(
        "/hsrl/ssjy/{symbol}/{licence}",
        "public realtime quote for one stock",
        required=("symbol",),
    ),
    "stock-ticks": BiyingEndpoint(
        "/hsrl/zbjy/{symbol}/{licence}",
        "current-day tick trades for one stock",
        required=("symbol",),
    ),
    "stock-realtime": BiyingEndpoint(
        "/hsstock/real/time/{symbol}/{licence}",
        "realtime quote for one stock",
        required=("symbol",),
    ),
    "stock-five": BiyingEndpoint(
        "/hsstock/real/five/{symbol}/{licence}",
        "level-5 order book for one stock",
        required=("symbol",),
    ),
    "stock-realtime-more": BiyingEndpoint(
        "/hsrl/ssjy_more/{licence}",
        "realtime quotes for multiple stocks",
        required=("stock_codes",),
        query=("stock_codes",),
    ),
    "stock-all-broker": BiyingEndpoint(
        "/hsrl/ssjy/all/{licence}",
        "all-stock realtime quotes from broker feed",
        base_url="https://all.biyingapi.com",
    ),
    "stock-all-network": BiyingEndpoint(
        "/hsrl/real/all/{licence}",
        "all-stock realtime quotes from network feed",
        base_url="https://all.biyingapi.com",
    ),
    "fund-flow": BiyingEndpoint(
        "/hsstock/history/transaction/{symbol}/{licence}",
        "stock capital-flow transaction data",
        required=("symbol",),
        query=("st", "et", "lt"),
    ),
    "stock-latest": BiyingEndpoint(
        "/hsstock/latest/{market_symbol}/{period}/{adjust}/{licence}",
        "latest stock bars",
        required=("market_symbol", "period", "adjust"),
        query=("lt",),
    ),
    "stock-history": BiyingEndpoint(
        "/hsstock/history/{market_symbol}/{period}/{adjust}/{licence}",
        "historical stock bars",
        required=("market_symbol", "period", "adjust"),
        query=("st", "et", "lt"),
    ),
    "stop-price-history": BiyingEndpoint(
        "/hsstock/stopprice/history/{market_symbol}/{licence}",
        "historical limit-up and limit-down prices",
        required=("market_symbol",),
        query=("st", "et"),
    ),
    "quote-indicators": BiyingEndpoint(
        "/hsstock/indicators/{market_symbol}/{licence}",
        "market quote indicators",
        required=("market_symbol",),
        query=("st", "et"),
    ),
    "stock-tech-macd": BiyingEndpoint(
        "/hsstock/history/macd/{market_symbol}/{period}/{adjust}/{licence}",
        "historical stock MACD indicator",
        required=("market_symbol", "period", "adjust"),
        query=("st", "et", "lt"),
    ),
    "stock-tech-ma": BiyingEndpoint(
        "/hsstock/history/ma/{market_symbol}/{period}/{adjust}/{licence}",
        "historical stock MA indicator",
        required=("market_symbol", "period", "adjust"),
        query=("st", "et", "lt"),
    ),
    "stock-tech-boll": BiyingEndpoint(
        "/hsstock/history/boll/{market_symbol}/{period}/{adjust}/{licence}",
        "historical stock BOLL indicator",
        required=("market_symbol", "period", "adjust"),
        query=("st", "et", "lt"),
    ),
    "stock-tech-kdj": BiyingEndpoint(
        "/hsstock/history/kdj/{market_symbol}/{period}/{adjust}/{licence}",
        "historical stock KDJ indicator",
        required=("market_symbol", "period", "adjust"),
        query=("st", "et", "lt"),
    ),
    # Financial statements and holder tables with date ranges.
    "instrument": BiyingEndpoint(
        "/hsstock/instrument/{market_symbol}/{licence}",
        "stock instrument metadata",
        required=("market_symbol",),
    ),
    "financial-balance": BiyingEndpoint(
        "/hsstock/financial/balance/{market_symbol}/{licence}",
        "balance sheet",
        required=("market_symbol",),
        query=("st", "et"),
    ),
    "financial-income": BiyingEndpoint(
        "/hsstock/financial/income/{market_symbol}/{licence}",
        "income statement",
        required=("market_symbol",),
        query=("st", "et"),
    ),
    "financial-cashflow": BiyingEndpoint(
        "/hsstock/financial/cashflow/{market_symbol}/{licence}",
        "cash-flow statement",
        required=("market_symbol",),
        query=("st", "et"),
    ),
    "financial-pershareindex": BiyingEndpoint(
        "/hsstock/financial/pershareindex/{market_symbol}/{licence}",
        "per-share and key financial indicators",
        required=("market_symbol",),
        query=("st", "et"),
    ),
    "capital": BiyingEndpoint(
        "/hsstock/financial/capital/{market_symbol}/{licence}",
        "share capital table",
        required=("market_symbol",),
        query=("st", "et"),
    ),
    "financial-topholder": BiyingEndpoint(
        "/hsstock/financial/topholder/{market_symbol}/{licence}",
        "top shareholders with date range",
        required=("market_symbol",),
        query=("st", "et"),
    ),
    "financial-flowholder": BiyingEndpoint(
        "/hsstock/financial/flowholder/{market_symbol}/{licence}",
        "top float shareholders with date range",
        required=("market_symbol",),
        query=("st", "et"),
    ),
    "holder-count": BiyingEndpoint(
        "/hsstock/financial/hm/{market_symbol}/{licence}",
        "shareholder count with date range",
        required=("market_symbol",),
        query=("st", "et"),
    ),
    # Index and fund datasets.
    "index-list": BiyingEndpoint("/hsindex/list/{licence}", "major A-share index list"),
    "index-realtime": BiyingEndpoint(
        "/hsindex/real/time/{index}/{licence}",
        "realtime index quote",
        required=("index",),
    ),
    "index-latest": BiyingEndpoint(
        "/hsindex/latest/{index}/{period}/{licence}",
        "latest index bars",
        required=("index", "period"),
        query=("lt",),
    ),
    "index-history": BiyingEndpoint(
        "/hsindex/history/{index}/{period}/{licence}",
        "historical index bars",
        required=("index", "period"),
        query=("st", "et", "lt"),
    ),
    "index-tech-macd": BiyingEndpoint(
        "/hsindex/history/macd/{index}/{period}/{licence}",
        "historical index MACD indicator",
        required=("index", "period"),
        query=("st", "et", "lt"),
    ),
    "index-tech-ma": BiyingEndpoint(
        "/hsindex/history/ma/{index}/{period}/{licence}",
        "historical index MA indicator",
        required=("index", "period"),
        query=("st", "et", "lt"),
    ),
    "index-tech-boll": BiyingEndpoint(
        "/hsindex/history/boll/{index}/{period}/{licence}",
        "historical index BOLL indicator",
        required=("index", "period"),
        query=("st", "et", "lt"),
    ),
    "index-tech-kdj": BiyingEndpoint(
        "/hsindex/history/kdj/{index}/{period}/{licence}",
        "historical index KDJ indicator",
        required=("index", "period"),
        query=("st", "et", "lt"),
    ),
    "fund-list": BiyingEndpoint("/fd/list/all/{licence}", "Shanghai and Shenzhen fund list"),
    "etf-list": BiyingEndpoint("/fd/list/etf/{licence}", "ETF fund list"),
    "fund-realtime": BiyingEndpoint(
        "/fd/real/time/{fund}/{licence}",
        "realtime fund quote",
        required=("fund",),
    ),
    # Beijing Stock Exchange and STAR Market.
    "bj-stock-list": BiyingEndpoint("/bj/list/all/{licence}", "Beijing stock list"),
    "bj-index-list": BiyingEndpoint("/bj/list/index/{licence}", "Beijing index list"),
    "bj-stock-realtime": BiyingEndpoint(
        "/bj/stock/real/time/{symbol}/{licence}",
        "Beijing stock realtime quote",
        required=("symbol",),
    ),
    "bj-stock-five": BiyingEndpoint(
        "/bj/stock/real/five/{symbol}/{licence}",
        "Beijing stock level-5 order book",
        required=("symbol",),
    ),
    "bj-index-realtime": BiyingEndpoint(
        "/bj/index/real/time/{index}/{licence}",
        "Beijing index realtime quote",
        required=("index",),
    ),
    "bj-history": BiyingEndpoint(
        "/bj/history/{market_symbol}/{period}/{adjust}/{licence}",
        "Beijing stock historical bars",
        required=("market_symbol", "period", "adjust"),
        query=("st", "et", "lt"),
    ),
    "bj-financial-balance": BiyingEndpoint(
        "/bj/financial/balance/{market_symbol}/{licence}",
        "Beijing balance sheet",
        required=("market_symbol",),
        query=("st", "et"),
    ),
    "bj-financial-income": BiyingEndpoint(
        "/bj/financial/income/{market_symbol}/{licence}",
        "Beijing income statement",
        required=("market_symbol",),
        query=("st", "et"),
    ),
    "bj-financial-cashflow": BiyingEndpoint(
        "/bj/financial/cashflow/{market_symbol}/{licence}",
        "Beijing cash-flow statement",
        required=("market_symbol",),
        query=("st", "et"),
    ),
    "bj-financial-pershareindex": BiyingEndpoint(
        "/bj/financial/pershareindex/{market_symbol}/{licence}",
        "Beijing per-share and key financial indicators",
        required=("market_symbol",),
        query=("st", "et"),
    ),
    "bj-capital": BiyingEndpoint(
        "/bj/financial/capital/{market_symbol}/{licence}",
        "Beijing share capital table",
        required=("market_symbol",),
        query=("st", "et"),
    ),
    "bj-financial-topholder": BiyingEndpoint(
        "/bj/financial/topholder/{market_symbol}/{licence}",
        "Beijing top shareholders with date range",
        required=("market_symbol",),
        query=("st", "et"),
    ),
    "bj-financial-flowholder": BiyingEndpoint(
        "/bj/financial/flowholder/{market_symbol}/{licence}",
        "Beijing top float shareholders with date range",
        required=("market_symbol",),
        query=("st", "et"),
    ),
    "bj-holder-count": BiyingEndpoint(
        "/bj/financial/hm/{market_symbol}/{licence}",
        "Beijing shareholder count with date range",
        required=("market_symbol",),
        query=("st", "et"),
    ),
    "kc-stock-list": BiyingEndpoint("/kc/list/all/{licence}", "STAR Market stock list"),
    "kc-stock-realtime": BiyingEndpoint(
        "/kc/real/time/{symbol}/{licence}",
        "STAR Market realtime quote",
        required=("symbol",),
    ),
    "kc-stock-five": BiyingEndpoint(
        "/kc/real/five/{symbol}/{licence}",
        "STAR Market level-5 order book",
        required=("symbol",),
    ),
}


def fetch_biying_dataset(
    *,
    dataset: str,
    params: dict[str, str | int | None],
    licences_value: str | None = None,
    base_url: str = DEFAULT_BIYING_BASE_URL,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    limit: int | None = None,
) -> dict[str, object]:
    """Fetch one mapped Biying dataset and return an AMStock JSON payload."""

    endpoint = endpoint_for_dataset(dataset)
    base_url = resolve_biying_base_url(base_url)
    timeout = resolve_biying_timeout(timeout)
    licences = rotate_biying_licences(load_biying_licences(licences_value))
    normalized_params = normalize_biying_params(params)
    request_params = select_biying_params(endpoint, normalized_params)
    url = build_biying_url(
        endpoint,
        params=request_params,
        licence=licences[0],
        base_url=base_url,
    )
    attempted_urls: list[str] = []
    last_error: Exception | None = None

    for licence in licences:
        url = build_biying_url(
            endpoint,
            params=request_params,
            licence=licence,
            base_url=base_url,
        )
        attempted_urls.append(redact_biying_url(url, licence))
        try:
            data = request_biying_json(url, timeout=timeout)
            return biying_payload(
                dataset=dataset,
                endpoint=endpoint,
                params=request_params,
                url=redact_biying_url(url, licence),
                data=data,
                limit=limit,
                licence_count=len(licences),
                attempted_urls=attempted_urls,
            )
        except Exception as exc:
            last_error = exc
            if not should_retry_biying_error(exc):
                break

    if last_error is None:
        msg = "Biying request failed before any HTTP attempt"
        raise RuntimeError(msg)
    raise last_error


def endpoint_for_dataset(dataset: str) -> BiyingEndpoint:
    """Return endpoint metadata for a dataset name."""

    try:
        return BIYING_ENDPOINTS[dataset]
    except KeyError as exc:
        choices = ", ".join(sorted(BIYING_ENDPOINTS))
        msg = f"unsupported Biying dataset {dataset!r}; choose one of: {choices}"
        raise ValueError(msg) from exc


def load_biying_licences(value: str | None = None) -> list[str]:
    """Load one or more Biying licences from an option value or environment."""

    raw = value
    if raw is None:
        raw = os.environ.get(BIYING_LICENCE_ENV) or os.environ.get(BIYING_LEGACY_LICENCE_ENV)
    if raw is None:
        configured = load_configured_biying_licences()
        if configured:
            return configured
    licences = [item for item in re.split(r"[\s,;]+", raw or "") if item]
    if not licences:
        msg = (
            "Biying licence is required; pass --licences, set "
            f"{BIYING_LICENCE_ENV}=licence1,licence2, or configure "
            "credentials.biying.licences in AMSTOCK_HOME/config/config.toml"
        )
        raise ValueError(msg)
    return licences


def load_configured_biying_licences() -> list[str]:
    """Load Biying licences from AMStock config when available."""

    try:
        return list(load_settings().biying_licences)
    except ConfigurationError:
        return []


def resolve_biying_base_url(value: str) -> str:
    """Resolve the Biying base URL from config when the default is used."""

    if value != DEFAULT_BIYING_BASE_URL:
        return value
    try:
        return load_settings().biying_base_url
    except ConfigurationError:
        return value


def resolve_biying_timeout(value: float) -> float:
    """Resolve Biying timeout from config when the default is used."""

    if value != DEFAULT_TIMEOUT_SECONDS:
        return value
    try:
        return load_settings().biying_timeout
    except ConfigurationError:
        return value


def rotate_biying_licences(licences: list[str]) -> list[str]:
    """Rotate licence order across CLI invocations when a state file is configured."""

    if len(licences) < 2:
        return licences

    state_path = biying_rotation_state_path()
    if state_path is None:
        return licences

    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        index = read_biying_rotation_index(state_path) % len(licences)
        write_biying_rotation_index(state_path, (index + 1) % len(licences))
    except OSError:
        return licences

    return [*licences[index:], *licences[:index]]


def biying_rotation_state_path() -> Path | None:
    """Return the configured Biying licence rotation state file."""

    explicit = os.environ.get(BIYING_ROTATION_FILE_ENV)
    if explicit and explicit.strip():
        return Path(explicit).expanduser()

    return amstock_home() / "data" / "biying_licence_rotation.json"


def read_biying_rotation_index(path: Path) -> int:
    """Read the next licence index from a rotation state file."""

    if not path.exists():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return 0
    if not isinstance(data, dict):
        return 0
    value = data.get("next_index")
    return value if isinstance(value, int) and value >= 0 else 0


def write_biying_rotation_index(path: Path, index: int) -> None:
    """Persist the next licence index."""

    path.write_text(json.dumps({"next_index": index}, ensure_ascii=False), encoding="utf-8")


def normalize_biying_params(params: dict[str, str | int | None]) -> dict[str, str]:
    """Normalize common Biying path and query parameters."""

    normalized: dict[str, str] = {}
    for key, value in params.items():
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        if key == "symbol":
            normalized[key] = normalize_biying_plain_symbol(text)
        elif key == "market_symbol":
            normalized[key] = normalize_biying_market_symbol(text)
        elif key == "index":
            normalized[key] = normalize_biying_index_symbol(text)
        elif key == "stock_codes":
            normalized[key] = ",".join(
                normalize_biying_plain_symbol(item) for item in split_codes(text)
            )
        else:
            normalized[key] = text
    return normalized


def select_biying_params(
    endpoint: BiyingEndpoint,
    params: dict[str, str],
) -> dict[str, str]:
    """Return only parameters used by an endpoint."""

    keys = (*endpoint.required, *endpoint.query)
    return {key: params[key] for key in keys if key in params}


def normalize_biying_plain_symbol(symbol: str) -> str:
    """Return a six-digit stock code without exchange prefix or market suffix."""

    normalized = symbol.strip().lower()
    if "." in normalized:
        normalized = normalized.split(".", maxsplit=1)[0]
    return normalize_a_stock_code(normalized)


def normalize_biying_market_symbol(symbol: str) -> str:
    """Return a Biying market symbol such as ``600519.SH`` or ``000001.SZ``."""

    normalized = symbol.strip().upper()
    if "." in normalized:
        code, market = normalized.split(".", maxsplit=1)
        return f"{normalize_a_stock_code(code)}.{normalize_biying_market(market)}"

    code = normalize_a_stock_code(normalized)
    if code.startswith("6"):
        return f"{code}.SH"
    if code.startswith(("0", "2", "3")):
        return f"{code}.SZ"
    if code.startswith(("4", "8", "9")):
        return f"{code}.BJ"

    msg = f"cannot infer Biying market suffix for {symbol!r}"
    raise ValueError(msg)


def normalize_biying_index_symbol(symbol: str) -> str:
    """Normalize an index symbol while requiring an explicit market suffix when ambiguous."""

    normalized = symbol.strip().upper()
    if "." not in normalized:
        msg = "Biying index datasets require an explicit suffix, e.g. 000001.SH"
        raise ValueError(msg)
    code, market = normalized.split(".", maxsplit=1)
    if not code.isdigit() or len(code) != 6:
        msg = f"expected a 6-digit index code, got {symbol!r}"
        raise ValueError(msg)
    return f"{code}.{normalize_biying_market(market)}"


def normalize_biying_market(value: str) -> str:
    """Normalize a Biying market suffix."""

    market = value.strip().upper()
    if market not in {"SH", "SZ", "BJ"}:
        msg = f"unsupported Biying market suffix {value!r}"
        raise ValueError(msg)
    return market


def split_codes(value: str) -> list[str]:
    """Split comma, semicolon, or whitespace separated stock codes."""

    return [item for item in re.split(r"[\s,;]+", value) if item]


def build_biying_url(
    endpoint: BiyingEndpoint,
    *,
    params: dict[str, str],
    licence: str,
    base_url: str = DEFAULT_BIYING_BASE_URL,
) -> str:
    """Build a Biying URL from endpoint metadata and normalized params."""

    values = {**params, "licence": licence}
    missing = [key for key in endpoint.required if key not in values]
    if missing:
        msg = f"missing required Biying parameter(s): {', '.join(missing)}"
        raise ValueError(msg)

    path = endpoint.path
    for key in (*endpoint.required, "licence"):
        value = values[key]
        path = path.replace(f"{{{key}}}", quote(value, safe=""))

    query = {
        key: values[key]
        for key in endpoint.query
        if key in values and values[key] not in {"", "None"}
    }
    query_text = urlencode(query, doseq=False)
    prefix = (endpoint.base_url or base_url).rstrip("/")
    return f"{prefix}{path}" if not query_text else f"{prefix}{path}?{query_text}"


def request_biying_json(url: str, *, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> JsonValue:
    """Request a Biying URL and parse JSON."""

    request = Request(url, headers={"User-Agent": "AMStock/0.1"})
    with urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8-sig")
    try:
        return cast("JsonValue", json.loads(raw))
    except json.JSONDecodeError as exc:
        msg = "Biying response was not valid JSON"
        raise ValueError(msg) from exc


def should_retry_biying_error(error: Exception) -> bool:
    """Return whether a Biying request should try the next licence."""

    if isinstance(error, HTTPError):
        return error.code in RETRYABLE_HTTP_STATUS
    return isinstance(error, URLError)


def biying_payload(
    *,
    dataset: str,
    endpoint: BiyingEndpoint,
    params: dict[str, str],
    url: str,
    data: JsonValue,
    limit: int | None,
    licence_count: int,
    attempted_urls: list[str],
) -> dict[str, object]:
    """Build a JSON-serializable AMStock payload from Biying data."""

    rows, returned_rows, columns, payload_data = limit_biying_data(data, limit=limit)
    return {
        "ok": True,
        "source": "biying",
        "function": dataset,
        "dataset": dataset,
        "description": endpoint.description,
        "params": params,
        "url": url,
        "licence_count": licence_count,
        "attempted_urls": attempted_urls,
        "rows": rows,
        "returned_rows": returned_rows,
        "columns": columns,
        "data": payload_data,
    }


def limit_biying_data(
    data: JsonValue,
    *,
    limit: int | None,
) -> tuple[int | None, int | None, list[str], JsonValue]:
    """Limit tabular Biying data and infer row and column metadata."""

    if isinstance(data, list):
        limited = data[:limit] if limit is not None else data
        return len(data), len(limited), infer_columns(limited), limited

    if isinstance(data, dict):
        nested = data.get("data")
        if isinstance(nested, list):
            limited_nested = nested[:limit] if limit is not None else nested
            limited = {**data, "data": limited_nested}
            return len(nested), len(limited_nested), infer_columns(limited_nested), limited
        return 1, 1, [str(key) for key in data], data

    return None, None, [], data


def infer_columns(records: list[JsonValue]) -> list[str]:
    """Infer columns from a list of dictionaries."""

    columns: list[str] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        for key in record:
            text = str(key)
            if text not in columns:
                columns.append(text)
    return columns


def redact_biying_url(url: str, licence: str) -> str:
    """Return a URL safe for logs and JSON output."""

    return url.replace(quote(licence, safe=""), "***").replace(licence, "***")
