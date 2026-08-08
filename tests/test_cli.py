"""Tests for the unified AMStock CLI."""

from __future__ import annotations

import json
import tomllib
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from amstock import cli

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

ADMIN_TOKEN = "test-admin-token"


def test_unified_cli_mounts_market_snapshot_commands() -> None:
    """The root command exposes the full-market snapshot command group."""

    result = CliRunner().invoke(cli.app, ["market-snapshot", "--help"])

    assert result.exit_code == 0
    assert "import" in result.stdout
    assert "list" in result.stdout


def test_unified_stock_basic_command_routes_to_source_function(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The unified stock command keeps the JSON source-query contract."""

    def fake_fetch_stock_basic(
        *,
        symbol: str,
        limit: int | None,
        no_proxy: bool,
        ipv4: bool,
    ) -> dict[str, object]:
        return {
            "ok": True,
            "source": "test",
            "function": "stock-basic",
            "params": {
                "symbol": symbol,
                "limit": limit,
                "no_proxy": no_proxy,
                "ipv4": ipv4,
            },
            "data": [],
        }

    monkeypatch.setattr(cli, "fetch_stock_basic", fake_fetch_stock_basic)

    result = CliRunner().invoke(
        cli.app,
        ["stock", "basic", "--symbol", "600519", "--limit", "2", "--no-proxy", "--ipv4"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["params"] == {
        "symbol": "600519",
        "limit": 2,
        "no_proxy": True,
        "ipv4": True,
    }


def test_unified_quote_pool_routes_to_biying(monkeypatch: pytest.MonkeyPatch) -> None:
    """Quote pool commands use the Biying dataset mapper."""

    def fake_fetch_biying_dataset(
        *,
        dataset: str,
        params: dict[str, str | int | None],
        licences_value: str | None,
        base_url: str,
        timeout: float,
        limit: int | None,
    ) -> dict[str, object]:
        return {
            "ok": True,
            "source": "biying-test",
            "function": dataset,
            "params": params,
            "licences_value": licences_value,
            "base_url": base_url,
            "timeout": timeout,
            "limit": limit,
            "data": [],
        }

    monkeypatch.setattr(cli, "fetch_biying_dataset", fake_fetch_biying_dataset)

    result = CliRunner().invoke(
        cli.app,
        [
            "quote",
            "pool",
            "--kind",
            "limit-up",
            "--date",
            "2024-01-10",
            "--licences",
            "alpha,beta",
            "--limit",
            "3",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["function"] == "limit-up-pool"
    assert payload["params"] == {"date": "2024-01-10"}
    assert payload["licences_value"] == "alpha,beta"
    assert payload["limit"] == 3


def test_stock_profile_routes_to_biying(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stock profile is exposed as a unified business command."""

    monkeypatch.setattr(cli, "fetch_biying_dataset", fake_biying_dataset)

    result = CliRunner().invoke(
        cli.app,
        ["stock", "profile", "--symbol", "000063", "--licences", "lic-1"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["function"] == "company-profile"
    assert payload["params"] == {"symbol": "000063"}


def test_stock_tech_routes_indicator_to_dataset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stock technical indicators select the matching Biying dataset."""

    monkeypatch.setattr(cli, "fetch_biying_dataset", fake_biying_dataset)

    result = CliRunner().invoke(
        cli.app,
        [
            "stock",
            "tech",
            "--symbol",
            "000063",
            "--indicator",
            "macd",
            "--period",
            "d",
            "--adjust",
            "q",
            "--lt",
            "20",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["function"] == "stock-tech-macd"
    assert payload["params"] == {
        "market_symbol": "000063",
        "period": "d",
        "adjust": "q",
        "st": None,
        "et": None,
        "lt": 20,
    }


def test_quote_batch_routes_symbols_to_biying(monkeypatch: pytest.MonkeyPatch) -> None:
    """Multi-stock realtime quotes keep the comma-separated symbol list."""

    monkeypatch.setattr(cli, "fetch_biying_dataset", fake_biying_dataset)

    result = CliRunner().invoke(
        cli.app,
        ["quote", "batch", "--symbols", "000063,600519", "--limit", "2"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["function"] == "stock-realtime-more"
    assert payload["params"] == {"stock_codes": "000063,600519"}
    assert payload["limit"] == 2


def test_quote_all_routes_selected_feed(monkeypatch: pytest.MonkeyPatch) -> None:
    """All-market quotes select the broker or network endpoint."""

    monkeypatch.setattr(cli, "fetch_biying_dataset", fake_biying_dataset)

    result = CliRunner().invoke(
        cli.app,
        ["quote", "all", "--source", "biying", "--feed", "network", "--limit", "5000"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["function"] == "stock-all-network"
    assert payload["limit"] == 5000


def test_quote_all_can_use_sina_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """All-market quotes can skip Biying and use AKShare Sina directly."""

    monkeypatch.setattr(cli, "_akshare_dataframe", fake_akshare_dataframe)

    result = CliRunner().invoke(
        cli.app,
        ["quote", "all", "--source", "sina", "--limit", "5"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["function"] == "stock_zh_a_spot"
    assert payload["limit"] == 5


def test_quote_all_auto_falls_back_to_sina(monkeypatch: pytest.MonkeyPatch) -> None:
    """Auto all-market quotes use Sina when the Biying all-market endpoint is unavailable."""

    def fake_fetch_quote_all(**_: object) -> dict[str, object]:
        raise RuntimeError("HTTP Error 429: Too Many Requests")

    monkeypatch.setattr(cli, "_fetch_quote_all", fake_fetch_quote_all)
    monkeypatch.setattr(cli, "_akshare_dataframe", fake_akshare_dataframe)

    result = CliRunner().invoke(cli.app, ["quote", "all", "--limit", "5"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["function"] == "stock_zh_a_spot"
    assert payload["fallback_from"]["function"] == "stock-all-network"


def test_us_quote_routes_to_twelvedata(monkeypatch: pytest.MonkeyPatch) -> None:
    """US quote commands pass Twelve Data credentials and proxy settings through."""

    def fake_fetch_twelvedata_quote(
        *,
        symbol: str,
        api_key: str | None,
        base_url: str | None,
        timeout: float | None,
        proxy_url: str | None,
    ) -> dict[str, object]:
        return {
            "ok": True,
            "source": "twelvedata-test",
            "function": "quote",
            "params": {
                "symbol": symbol,
                "api_key": api_key,
                "base_url": base_url,
                "timeout": timeout,
                "proxy_url": proxy_url,
            },
            "data": {},
        }

    monkeypatch.setattr(cli, "fetch_twelvedata_quote", fake_fetch_twelvedata_quote)

    result = CliRunner().invoke(
        cli.app,
        [
            "us",
            "quote",
            "--symbol",
            "NVDA",
            "--api-key",
            "key-1",
            "--base-url",
            "https://example.test",
            "--timeout",
            "7",
            "--proxy-url",
            "http://127.0.0.1:7897",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["function"] == "quote"
    assert payload["params"] == {
        "symbol": "NVDA",
        "api_key": "key-1",
        "base_url": "https://example.test",
        "timeout": 7.0,
        "proxy_url": "http://127.0.0.1:7897",
    }


def test_us_history_routes_to_twelvedata(monkeypatch: pytest.MonkeyPatch) -> None:
    """US history commands map CLI options to Twelve Data time_series."""

    def fake_fetch_twelvedata_time_series(
        *,
        symbol: str,
        interval: str,
        outputsize: int | None,
        start_date: str | None,
        end_date: str | None,
        api_key: str | None,
        base_url: str | None,
        timeout: float | None,
        proxy_url: str | None,
    ) -> dict[str, object]:
        return {
            "ok": True,
            "source": "twelvedata-test",
            "function": "time_series",
            "params": {
                "symbol": symbol,
                "interval": interval,
                "outputsize": outputsize,
                "start_date": start_date,
                "end_date": end_date,
                "api_key": api_key,
                "base_url": base_url,
                "timeout": timeout,
                "proxy_url": proxy_url,
            },
            "data": [],
        }

    monkeypatch.setattr(cli, "fetch_twelvedata_time_series", fake_fetch_twelvedata_time_series)

    result = CliRunner().invoke(
        cli.app,
        [
            "us",
            "history",
            "--symbol",
            "MSFT",
            "--interval",
            "1day",
            "--outputsize",
            "20",
            "--start-date",
            "2026-06-01",
            "--end-date",
            "2026-06-10",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["function"] == "time_series"
    assert payload["params"]["symbol"] == "MSFT"
    assert payload["params"]["interval"] == "1day"
    assert payload["params"]["outputsize"] == 20
    assert payload["params"]["start_date"] == "2026-06-01"
    assert payload["params"]["end_date"] == "2026-06-10"


def test_quote_breadth_calculates_market_width(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Breadth is derived locally from all-market realtime quotes."""

    def fake_fetch_quote_all(**_: object) -> dict[str, object]:
        return {
            "ok": True,
            "dataset": "stock-all-network",
            "rows": 5,
            "data": [
                {"dm": "000001", "zf": "1.5"},
                {"dm": "000002", "zf": "-6.0"},
                {"dm": "000003", "zf": "0"},
                {"dm": "000004", "zf": "9.5"},
                {"dm": "000005", "zf": "-9.1"},
            ],
        }

    monkeypatch.setattr(cli, "_fetch_quote_all", fake_fetch_quote_all)

    result = CliRunner().invoke(cli.app, ["quote", "breadth"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    summary = payload["data"][0]
    assert summary["up"] == 2
    assert summary["down"] == 2
    assert summary["flat"] == 1
    assert summary["up_gte_9"] == 1
    assert summary["down_lte_minus_9"] == 1
    assert summary["median_change_percent"] == 0.0


def test_quote_breadth_falls_back_to_akshare(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Breadth uses AKShare if Biying all-market quotes fail."""

    def fake_fetch_quote_all(**_: object) -> dict[str, object]:
        raise RuntimeError("certificate mismatch")

    def fake_akshare_dataframe(
        function: str,
        params: dict[str, object],
        **_: object,
    ) -> dict[str, object]:
        return {
            "ok": True,
            "source": "akshare-test",
            "function": function,
            "params": params,
            "rows": 2,
            "data": [{"涨跌幅": "1.0"}, {"涨跌幅": "-2.0"}],
        }

    monkeypatch.setattr(cli, "_fetch_quote_all", fake_fetch_quote_all)
    monkeypatch.setattr(cli, "_akshare_dataframe", fake_akshare_dataframe)

    result = CliRunner().invoke(cli.app, ["quote", "breadth"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["fallback_from"]["function"] == "stock-all-network"
    assert payload["data"][0]["up"] == 1
    assert payload["data"][0]["down"] == 1


def test_quote_sentiment_combines_pools_and_breadth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sentiment combines pool row counts with local breadth."""

    def fake_fetch_biying(
        dataset: str,
        params: dict[str, object],
        **_: object,
    ) -> dict[str, object]:
        _ = params
        data = {
            "limit-up-pool": [{"lbc": "2"}, {"lbc": "3"}],
            "limit-down-pool": [{}],
            "strong-pool": [{}, {}, {}],
            "limit-break-pool": [{}],
        }[dataset]
        return {"ok": True, "rows": len(data), "data": data}

    def fake_fetch_quote_all(**_: object) -> dict[str, object]:
        return {"ok": True, "rows": 2, "data": [{"zf": "1"}, {"zf": "-1"}]}

    monkeypatch.setattr(cli, "_fetch_biying", fake_fetch_biying)
    monkeypatch.setattr(cli, "_fetch_quote_all", fake_fetch_quote_all)

    result = CliRunner().invoke(
        cli.app,
        ["quote", "sentiment", "--date", "2026-06-05"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    summary = payload["data"][0]
    assert summary["limit_up"] == 2
    assert summary["limit_down"] == 1
    assert summary["strong"] == 3
    assert summary["limit_break"] == 1
    assert summary["limit_break_rate"] == 0.333333
    assert summary["highest_board_count"] == 3.0
    assert summary["breadth"]["up"] == 1


def test_quote_sentiment_keeps_working_when_breadth_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sentiment does not fail just because the all-market quote subdomain is broken."""

    def fake_fetch_biying(
        dataset: str,
        params: dict[str, object],
        **_: object,
    ) -> dict[str, object]:
        _ = params
        data = {
            "limit-up-pool": [{}],
            "limit-down-pool": [],
            "strong-pool": [],
            "limit-break-pool": [],
        }[dataset]
        return {"ok": True, "rows": len(data), "data": data}

    def fake_fetch_quote_all(**_: object) -> dict[str, object]:
        raise RuntimeError("certificate mismatch")

    def fake_akshare_dataframe(
        function: str,
        params: dict[str, object],
        **_: object,
    ) -> dict[str, object]:
        return {
            "ok": True,
            "source": "akshare-test",
            "function": function,
            "params": params,
            "rows": 1,
            "data": [{"涨跌幅": "0"}],
        }

    monkeypatch.setattr(cli, "_fetch_biying", fake_fetch_biying)
    monkeypatch.setattr(cli, "_fetch_quote_all", fake_fetch_quote_all)
    monkeypatch.setattr(cli, "_akshare_dataframe", fake_akshare_dataframe)

    result = CliRunner().invoke(
        cli.app,
        ["quote", "sentiment", "--date", "2026-06-05"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["fallback_from"]["function"] == "stock-all-network"
    assert payload["data"][0]["limit_up"] == 1
    assert payload["data"][0]["breadth"]["flat"] == 1


def test_quote_flow_summary_aggregates_recent_days(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flow summary aggregates Biying active buy/sell amount fields."""

    def fake_fetch_biying_dataset(**kwargs: object) -> dict[str, object]:
        return {
            "ok": True,
            "source": "biying-test",
            "function": kwargs["dataset"],
            "params": kwargs["params"],
            "rows": 3,
            "data": [
                {
                    "t": "2026-06-03",
                    "zmbtdcjzl": "100",
                    "zmstdcjzl": "50",
                    "zmbddcjzl": "80",
                    "zmsddcjzl": "20",
                },
                {
                    "t": "2026-06-05",
                    "zmbtdcjzl": "90",
                    "zmstdcjzl": "10",
                    "zmbddcjzl": "20",
                    "zmsddcjzl": "5",
                },
                {
                    "t": "2026-06-04",
                    "zmbtdcjzl": "10",
                    "zmstdcjzl": "60",
                    "zmbddcjzl": "5",
                    "zmsddcjzl": "40",
                },
            ],
        }

    monkeypatch.setattr(cli, "fetch_biying_dataset", fake_fetch_biying_dataset)

    result = CliRunner().invoke(
        cli.app,
        ["quote", "flow-summary", "--symbol", "000063", "--days", "2"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    summary = payload["data"][0]
    assert payload["function"] == "quote-flow-summary"
    assert summary["records_used"] == 2
    assert summary["main_net_1d"] == 95.0
    assert summary["main_net_3d"] == 10.0
    assert summary["super_large_net_amount"] == 30.0
    assert summary["large_net_amount"] == -20.0
    assert summary["consecutive_flow_days"] == 1


def test_index_intraday_routes_symbol_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    """Index intraday supports --symbol as an alias for --index."""

    monkeypatch.setattr(cli, "fetch_biying_dataset", fake_biying_dataset)

    result = CliRunner().invoke(
        cli.app,
        ["index", "intraday", "--symbol", "000001.SH", "--period", "1"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["function"] == "index-latest"
    assert payload["params"] == {"index": "000001.SH", "period": "1", "lt": None}


def test_index_quote_auto_falls_back_to_akshare(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Index quote falls back to AKShare when Biying realtime is unavailable."""

    def fake_biying_dataset(**_: object) -> dict[str, object]:
        raise RuntimeError("HTTP Error 503: Service Unavailable")

    def fake_akshare_dataframe(
        function: str,
        params: dict[str, object],
        **_: object,
    ) -> dict[str, object]:
        return {
            "ok": True,
            "source": "akshare-test",
            "function": function,
            "params": params,
            "rows": 2,
            "data": [{"代码": "000001", "名称": "上证指数"}, {"代码": "000002"}],
        }

    monkeypatch.setattr(cli, "fetch_biying_dataset", fake_biying_dataset)
    monkeypatch.setattr(cli, "_akshare_dataframe", fake_akshare_dataframe)

    result = CliRunner().invoke(cli.app, ["index", "quote", "--symbol", "000001.SH"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["function"] == "stock_zh_index_spot_em"
    assert payload["params"] == {"symbol": "上证系列指数", "filter_symbol": "000001"}
    assert payload["fallback_from"]["function"] == "index-realtime"
    assert payload["rows"] == 1


def test_index_tech_routes_indicator_to_dataset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Index technical indicators select the matching Biying dataset."""

    monkeypatch.setattr(cli, "fetch_biying_dataset", fake_biying_dataset)

    result = CliRunner().invoke(
        cli.app,
        ["index", "tech", "--symbol", "000001.SH", "--indicator", "ma"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["function"] == "index-tech-ma"
    assert payload["params"] == {
        "index": "000001.SH",
        "period": "d",
        "st": None,
        "et": None,
        "lt": None,
    }


def test_sector_flow_routes_to_tested_ths_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sector flow uses the tested THS AKShare functions."""

    monkeypatch.setattr(cli, "_akshare_dataframe", fake_akshare_dataframe)

    result = CliRunner().invoke(
        cli.app,
        ["sector", "flow", "--kind", "concept", "--period", "5d", "--limit", "10"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["function"] == "stock_fund_flow_concept"
    assert payload["params"] == {"symbol": "5日排行"}
    assert payload["limit"] == 10


def test_fund_share_change_routes_sse_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SSE ETF share-change uses the tested SSE scale function."""

    monkeypatch.setattr(cli, "_akshare_dataframe", fake_akshare_dataframe)

    result = CliRunner().invoke(
        cli.app,
        ["fund", "share-change", "--exchange", "sse", "--date", "20250115", "--limit", "2"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["function"] == "fund_etf_scale_sse"
    assert payload["params"] == {"date": "20250115"}
    assert payload["limit"] == 2


def test_fund_share_change_routes_szse_backup_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SZSE ETF share-change uses fund_scale_daily_szse instead of broken fund_etf_scale_szse."""

    monkeypatch.setattr(cli, "_akshare_dataframe", fake_akshare_dataframe)

    result = CliRunner().invoke(
        cli.app,
        ["fund", "share-change", "--exchange", "szse", "--date", "20260401"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["function"] == "fund_scale_daily_szse"
    assert payload["params"] == {
        "symbol": "ETF",
        "start_date": "20260401",
        "end_date": "20260401",
    }


def test_fund_share_change_accepts_symbol_and_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ETF share-change can infer SZSE from a fund symbol and filter the result."""

    def fake_akshare_dataframe(
        function: str,
        params: dict[str, object],
        **_: object,
    ) -> dict[str, object]:
        return {
            "ok": True,
            "source": "akshare-test",
            "function": function,
            "params": params,
            "rows": 2,
            "data": [{"基金代码": "159995"}, {"基金代码": "159996"}],
        }

    monkeypatch.setattr(cli, "_akshare_dataframe", fake_akshare_dataframe)

    result = CliRunner().invoke(
        cli.app,
        [
            "fund",
            "share-change",
            "--symbol",
            "159995",
            "--start-date",
            "20260601",
            "--end-date",
            "20260605",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["function"] == "fund_scale_daily_szse"
    assert payload["params"] == {
        "symbol": "ETF",
        "start_date": "20260601",
        "end_date": "20260605",
        "filter_symbol": "159995",
    }
    assert payload["rows"] == 1
    assert payload["data"] == [{"基金代码": "159995"}]


def test_fund_holdings_routes_to_eastmoney_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fund holdings use the tested Eastmoney fund portfolio source."""

    monkeypatch.setattr(cli, "_akshare_dataframe", fake_akshare_dataframe)

    result = CliRunner().invoke(
        cli.app,
        ["fund", "holdings", "--symbol", "159995", "--year", "2024"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["function"] == "fund_portfolio_hold_em"
    assert payload["params"] == {"symbol": "159995", "date": "2024"}


def test_fund_holding_summary_routes_to_cninfo_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fund holding summary exposes the tested CNInfo market-level source."""

    monkeypatch.setattr(cli, "_akshare_dataframe", fake_akshare_dataframe)

    result = CliRunner().invoke(
        cli.app,
        ["fund", "holding-summary", "--date", "20241231", "--limit", "5"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["function"] == "fund_report_stock_cninfo"
    assert payload["params"] == {"date": "20241231"}
    assert payload["limit"] == 5


def test_news_gdelt_routes_to_news_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    """GDELT news command passes endpoint filters and token through."""

    def fake_fetch_gdelt_news(
        *,
        endpoint: str,
        params: dict[str, object],
        token_value: str | None,
        base_url: str,
        timeout: float,
        limit: int | None,
    ) -> dict[str, object]:
        return {
            "ok": True,
            "source": "gdelt-test",
            "function": f"gdelt-{endpoint}",
            "params": params,
            "token_value": token_value,
            "base_url": base_url,
            "timeout": timeout,
            "limit": limit,
            "data": [],
        }

    monkeypatch.setattr(cli, "fetch_gdelt_news", fake_fetch_gdelt_news)

    result = CliRunner().invoke(
        cli.app,
        [
            "news",
            "gdelt",
            "--endpoint",
            "events",
            "--query",
            "central bank",
            "--country",
            "US",
            "--token",
            "gdelt-token",
            "--limit",
            "5",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["function"] == "gdelt-events"
    assert payload["params"]["search"] == "central bank"
    assert payload["params"]["country"] == "US"
    assert payload["token_value"] == "gdelt-token"
    assert payload["limit"] == 5


def test_news_gdelt_accepts_time_range_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    """GDELT news supports --from/--to as time-range aliases."""

    def fake_fetch_gdelt_news(
        *,
        endpoint: str,
        params: dict[str, object],
        token_value: str | None,
        base_url: str,
        timeout: float,
        limit: int | None,
    ) -> dict[str, object]:
        _ = endpoint, token_value, base_url, timeout, limit
        return {"ok": True, "params": params, "data": []}

    monkeypatch.setattr(cli, "fetch_gdelt_news", fake_fetch_gdelt_news)

    result = CliRunner().invoke(
        cli.app,
        [
            "news",
            "gdelt",
            "--query",
            "tariffs",
            "--from",
            "2026-06-01",
            "--to",
            "2026-06-08",
            "--token",
            "gdelt-token",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["params"]["date_start"] == "2026-06-01"
    assert payload["params"]["date_end"] == "2026-06-08"


def test_news_marketaux_routes_to_news_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    """Marketaux news command passes market filters and token through."""

    def fake_fetch_marketaux_news(
        *,
        params: dict[str, object],
        token_value: str | None,
        base_url: str,
        timeout: float,
        limit: int | None,
    ) -> dict[str, object]:
        return {
            "ok": True,
            "source": "marketaux-test",
            "function": "marketaux-news-all",
            "params": params,
            "token_value": token_value,
            "base_url": base_url,
            "timeout": timeout,
            "limit": limit,
            "data": [],
        }

    monkeypatch.setattr(cli, "fetch_marketaux_news", fake_fetch_marketaux_news)

    result = CliRunner().invoke(
        cli.app,
        [
            "news",
            "marketaux",
            "--query",
            "oil sanctions",
            "--symbols",
            "USO,CL=F",
            "--countries",
            "us",
            "--token",
            "marketaux-token",
            "--limit",
            "10",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["function"] == "marketaux-news-all"
    assert payload["params"]["search"] == "oil sanctions"
    assert payload["params"]["symbols"] == "USO,CL=F"
    assert payload["params"]["countries"] == "us"
    assert payload["params"]["filter_entities"] is True
    assert payload["token_value"] == "marketaux-token"
    assert payload["limit"] == 10


def test_news_marketaux_accepts_time_range_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    """Marketaux news supports --from/--to as publication time aliases."""

    def fake_fetch_marketaux_news(
        *,
        params: dict[str, object],
        token_value: str | None,
        base_url: str,
        timeout: float,
        limit: int | None,
    ) -> dict[str, object]:
        _ = token_value, base_url, timeout, limit
        return {"ok": True, "params": params, "data": []}

    monkeypatch.setattr(cli, "fetch_marketaux_news", fake_fetch_marketaux_news)

    result = CliRunner().invoke(
        cli.app,
        [
            "news",
            "marketaux",
            "--symbols",
            "NVDA",
            "--from",
            "2026-06-01T00:00",
            "--to",
            "2026-06-08T23:59",
            "--token",
            "marketaux-token",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["params"]["published_after"] == "2026-06-01T00:00"
    assert payload["params"]["published_before"] == "2026-06-08T23:59"


def test_news_server_commands_route_to_server_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    """News commands route to server helpers with new filter parameters."""

    monkeypatch.setattr(cli, "run_news_once", lambda: {"ok": True, "function": "news-once"})
    monkeypatch.setattr(
        cli,
        "news_list_payload",
        lambda **kwargs: {
            "ok": True,
            "function": "news-list",
            **kwargs,
        },
    )

    once = CliRunner().invoke(cli.app, ["news", "once"])
    list_result = CliRunner().invoke(
        cli.app,
        [
            "news",
            "list",
            "--limit", "9",
            "--source", "gdelt-policy",
            "--provider", "gdelt",
            "--query", "OPEC",
            "--since", "2026-06-08",
            "--category", "宏观经济",
            "--min-importance", "4",
            "--sort-by", "importance",
            "--sort-order", "desc",
        ],
    )

    assert once.exit_code == 0
    assert json.loads(once.stdout)["function"] == "news-once"
    assert list_result.exit_code == 0
    list_payload = json.loads(list_result.stdout)
    assert list_payload["function"] == "news-list"
    assert list_payload["limit"] == 9
    assert list_payload["source"] == "gdelt-policy"
    assert list_payload["provider"] == "gdelt"
    assert list_payload["query"] == "OPEC"
    assert list_payload["since"] == "2026-06-08"
    assert list_payload["category"] == "宏观经济"
    assert list_payload["min_importance"] == 4


def test_news_web_command_registered() -> None:
    """News web command is registered and accepts host/port options."""

    result = CliRunner().invoke(cli.app, ["news", "web", "--help"])
    assert result.exit_code == 0
    assert "--host" in result.stdout
    assert "--port" in result.stdout


def test_unified_sources_capabilities_keeps_legacy_source_app() -> None:
    """The old source CLI is available under the unified sources namespace."""

    result = CliRunner().invoke(cli.app, ["sources", "capabilities"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["cli"] == "amstock_src"


def test_config_init_creates_default_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The unified CLI can create AMSTOCK_HOME/config/config.toml."""

    monkeypatch.setenv("AMSTOCK_HOME", str(tmp_path))
    result = CliRunner().invoke(cli.app, ["config", "init"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["created"] is True
    assert (tmp_path / "config" / "config.toml").exists()

    second = CliRunner().invoke(cli.app, ["config", "init"])
    assert second.exit_code == 0
    assert json.loads(second.stdout)["created"] is False


def test_config_path_reports_primary_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The config path command reports the active AMStock config path."""

    monkeypatch.setenv("AMSTOCK_HOME", str(tmp_path))
    result = CliRunner().invoke(cli.app, ["config", "path"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["amstock_home"] == str(tmp_path)
    assert payload["config_path"] == str(tmp_path / "config" / "config.toml")


def test_unified_portfolio_namespace_mounts_store_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The portfolio namespace exposes the existing store commands."""

    configure_amstock_home(tmp_path, monkeypatch)
    runner = CliRunner()

    create = runner.invoke(
        cli.app,
        [
            "portfolio",
            "admin",
            "user",
            "create",
            "--username",
            "alice",
            "--admin-token",
            ADMIN_TOKEN,
        ],
    )
    assert create.exit_code == 0

    buy = runner.invoke(
        cli.app,
        [
            "portfolio",
            "trade",
            "buy",
            "--user",
            "alice",
            "--symbol",
            "600519",
            "--quantity",
            "100",
            "--price",
            "10",
        ],
    )
    assert buy.exit_code == 0

    summary = runner.invoke(
        cli.app,
        ["portfolio", "summary", "--user", "alice", "--mark", "600519=12"],
    )

    assert summary.exit_code == 0
    payload = json.loads(summary.stdout)
    assert payload["ok"] is True
    assert payload["positions"][0]["quantity"] == "100.0000"


def test_unified_sector_flow_namespace_is_mounted() -> None:
    """The unified CLI exposes the sector-flow command group."""

    result = CliRunner().invoke(cli.app, ["sector-flow", "--help"])

    assert result.exit_code == 0
    assert "import" in result.stdout
    assert "list" in result.stdout


def configure_amstock_home(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Create a config under a temporary AMSTOCK_HOME."""

    config_dir = root / "config"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        f"""
[database]
path = "data/store.sqlite3"

[credentials.store]
admin_token = "{ADMIN_TOKEN}"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("AMSTOCK_HOME", str(root))
    monkeypatch.delenv("AMSTOCK_ROOT", raising=False)


def fake_biying_dataset(
    *,
    dataset: str,
    params: dict[str, str | int | None],
    licences_value: str | None,
    base_url: str,
    timeout: float,
    limit: int | None,
) -> dict[str, object]:
    """Return the Biying call metadata for route tests."""

    return {
        "ok": True,
        "source": "biying-test",
        "function": dataset,
        "params": params,
        "licences_value": licences_value,
        "base_url": base_url,
        "timeout": timeout,
        "limit": limit,
        "data": [],
    }


def fake_akshare_dataframe(
    function: str,
    params: dict[str, object],
    *,
    limit: int | None,
    no_proxy: bool,
    ipv4: bool,
) -> dict[str, object]:
    """Return AKShare call metadata for route tests."""

    return {
        "ok": True,
        "source": "akshare-test",
        "function": function,
        "params": params,
        "limit": limit,
        "no_proxy": no_proxy,
        "ipv4": ipv4,
        "data": [],
    }
