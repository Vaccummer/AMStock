---
name: amstock-price-history
description: Fetch China A-share historical K-line price data through AKShare. Use when the user asks for A-share historical prices, daily/weekly/monthly OHLCV data, adjusted or unadjusted K-lines, recent candles, return calculations, or time-series data for analysis and backtesting.
---

# AMStock Price History

Use `scripts/price_history.py` from the AMStock project root. The script wraps `ak.stock_zh_a_hist` and emits JSON.
If Eastmoney requests fail because of local proxy or IPv6 routing, add `--no-proxy --ipv4`.
If AKShare raises a connection error, the script automatically falls back to BaoStock `query_history_k_data_plus` and includes `fallback_from` in the JSON payload.

Always choose an adjustment mode explicitly when the user cares about price continuity:

- `none`: unadjusted prices
- `qfq`: forward-adjusted prices
- `hfq`: backward-adjusted prices

## Commands

Fetch recent daily K-lines:

```powershell
uv run python skills/amstock-price-history/scripts/price_history.py --symbol 600519 --start-date 20250101 --end-date 20250511 --adjust qfq --limit 30
```

Fetch weekly or monthly data:

```powershell
uv run python skills/amstock-price-history/scripts/price_history.py --symbol 000001 --period weekly --adjust none --limit 20
uv run python skills/amstock-price-history/scripts/price_history.py --symbol 000001 --period monthly --adjust hfq --limit 20
```

## Mapping

- Script: `price_history.py`
- AKShare: `ak.stock_zh_a_hist(symbol, period, start_date, end_date, adjust)`
- Supported `period`: `daily`, `weekly`, `monthly`
- Supported `adjust`: `none`, `qfq`, `hfq`
- BaoStock fallback maps `daily/weekly/monthly` to `d/w/m` and `none/qfq/hfq` to `3/2/1`.

Treat AKShare data as reference data, not investment advice.
