---
name: amstock-price-history
description: Fetch China A-share and index historical K-line, intraday, historical intraday, limit-price, and technical indicator data through the unified AMStock CLI. Use when the user asks for A-share historical prices, daily/weekly/monthly OHLCV data, adjusted or unadjusted K-lines, recent candles, intraday bars, index bars, MACD/MA/BOLL/KDJ, return calculations, or time-series data for analysis and backtesting.
---

# AMStock Price History

Use `uv run amstock stock history ...` from the AMStock project root. The command emits JSON. It defaults to BaoStock for stable daily/weekly/monthly A-share K-lines and can use Biying with `--source biying`.
If BaoStock requests fail because of local proxy or IPv6 routing, add `--no-proxy --ipv4`.
For Biying, provide licences with `--licences`, `AMSTOCK_BIYING_LICENCES`, or `[credentials.biying] licences = [...]` in `AMSTOCK_HOME/config/config.toml`.

Always choose an adjustment mode explicitly when the user cares about price continuity:

- `none`: unadjusted prices
- `qfq`: forward-adjusted prices
- `hfq`: backward-adjusted prices

## Commands

Fetch recent daily K-lines:

```powershell
uv run amstock stock history --symbol 600519 --start-date 20250101 --end-date 20250511 --adjust qfq --limit 30
```

Fetch weekly or monthly data:

```powershell
uv run amstock stock history --symbol 000001 --period weekly --adjust none --limit 20
uv run amstock stock history --symbol 000001 --period monthly --adjust hfq --limit 20
```

Fetch Biying historical bars:

```powershell
uv run amstock stock history --source biying --symbol 000001 --st 20240601 --et 20240605 --lt 20 --licences licence1,licence2
uv run amstock quote intraday --symbol 000001 --period 1 --lt 240 --licences licence1,licence2
uv run amstock quote history-intraday --symbol 000001 --date 20240605 --period 1 --lt 240 --licences licence1,licence2
uv run amstock quote limit-price-history --symbol 000001 --st 20240601 --et 20240605 --licences licence1,licence2
uv run amstock stock indicators --symbol 000001 --st 20240601 --et 20240605 --limit 20 --licences licence1,licence2
uv run amstock stock tech --symbol 000001 --indicator macd --period d --adjust n --lt 20 --licences licence1,licence2
uv run amstock index history --symbol 000001.SH --st 20240601 --et 20240605 --lt 20 --licences licence1,licence2
uv run amstock index intraday --symbol 000001.SH --period 1 --lt 240 --licences licence1,licence2
uv run amstock index tech --symbol 000001.SH --indicator ma --period d --lt 20 --licences licence1,licence2
```

## Mapping

- Command: `amstock stock history`
- BaoStock: `query_history_k_data_plus`
- Biying: `stock-history`
- Biying intraday/history-intraday: `stock-latest` and `stock-history`
- Biying limit prices: `stop-price-history`
- Biying stock indicators and tech: `quote-indicators`, `stock-tech-*`
- Biying index history/intraday/tech: `index-history`, `index-latest`, `index-tech-*`
- Supported `period`: `daily`, `weekly`, `monthly`
- Supported `adjust`: `none`, `qfq`, `hfq`
- Biying mode maps `daily/weekly/monthly` to `d/w/m` and `none/qfq/hfq` to `n/q/h`.

Treat source data as reference data, not investment advice.
