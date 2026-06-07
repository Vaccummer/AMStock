---
name: amstock-market-quote
description: Fetch China A-share quotes, market-wide spot data, exchange summaries, order book snapshots, stock pools, capital-flow summaries, market breadth, sentiment summaries, index quotes, fund quotes, and individual stock basics through the unified AMStock CLI. Use when the user asks for current A-share prices, quote snapshots, stock basic information, Shanghai/Shenzhen market summaries, broad market strength, short-term market mood, ETF realtime quotes, or wants to inspect a stock before deeper analysis.
---

# AMStock Market Quote

Use `uv run amstock ...` from the AMStock project root. Commands return one JSON object with `ok`, `function`, `params`, row counts, columns, and `data`.

Prefer `--limit` for broad datasets so the answer stays readable.
If Eastmoney requests fail because of local proxy or IPv6 routing, add `--no-proxy --ipv4`.
For realtime quotes, level-5 order books, tick trades, stock pools, market breadth, sentiment, index quotes, and fund quotes, use Biying-backed commands. Provide Biying licences with `--licences`, `AMSTOCK_BIYING_LICENCES`, or `[credentials.biying] licences = [...]` in `AMSTOCK_HOME/config/config.toml`.

## Commands

Fetch all A-share spot quotes:

```powershell
uv run amstock stock list --limit 20
```

Fetch individual stock basics:

```powershell
uv run amstock stock basic --symbol 600519
uv run amstock stock basic --symbol 600519 --no-proxy --ipv4
```

Fetch exchange summaries:

```powershell
uv run amstock quote exchange-summary --exchange sse
uv run amstock quote exchange-summary --exchange szse --date 20240830
```

Fetch Biying realtime quote and level-5 order book:

```powershell
uv run amstock quote stock --symbol 000001 --licences licence1,licence2
uv run amstock quote five --symbol 000001 --licences licence1,licence2
uv run amstock quote ticks --symbol 000001 --licences licence1,licence2 --limit 20
uv run amstock quote batch --symbols 000063,600519 --licences licence1,licence2
uv run amstock quote all --feed network --licences licence1,licence2 --limit 5000
```

Fetch event stock pools:

```powershell
uv run amstock quote pool --kind limit-up --date 2024-01-10 --licences licence1,licence2 --limit 20
uv run amstock quote pool --kind failed-limit-up --date 2024-01-10 --licences licence1,licence2 --limit 20
```

Summarize capital flow, market breadth, and short-term sentiment:

```powershell
uv run amstock quote flow-summary --symbol 000063 --days 5 --licences licence1,licence2
uv run amstock quote breadth --licences licence1,licence2
uv run amstock quote sentiment --date 2024-01-10 --licences licence1,licence2
```

Fetch index and fund realtime quotes:

```powershell
uv run amstock index quote --symbol 000001.SH --licences licence1,licence2
uv run amstock fund quote --symbol 159995 --licences licence1,licence2
```

## Mapping

- `stock list`: BaoStock `query_all_stock(day=...)`
- `stock basic`: BaoStock `query_stock_basic(code=...)`
- `sse-summary`: `ak.stock_sse_summary()`
- `szse-summary`: `ak.stock_szse_summary(date=...)`
- `quote stock/five/ticks/batch/all/pool`: Biying API datasets
- `quote flow-summary`: Biying `fund-flow` plus local AMStock aggregation
- `quote breadth`: Biying all-market realtime quotes plus local AMStock aggregation
- `quote sentiment`: Biying stock pools plus local AMStock aggregation
- `index quote`: Biying `index-realtime`
- `fund quote`: Biying `fund-realtime`

Treat source data as reference data, not investment advice.
