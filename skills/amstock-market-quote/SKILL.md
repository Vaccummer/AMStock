---
name: amstock-market-quote
description: Fetch China A-share quotes, market-wide spot data, exchange summaries, order book snapshots, and individual stock basics through the unified AMStock CLI. Use when the user asks for current A-share prices, quote snapshots, stock basic information, Shanghai/Shenzhen market summaries, or wants to inspect a stock before deeper analysis.
---

# AMStock Market Quote

Use `uv run amstock ...` from the AMStock project root. Commands return one JSON object with `ok`, `function`, `params`, row counts, columns, and `data`.

Prefer `--limit` for broad datasets so the answer stays readable.
If Eastmoney requests fail because of local proxy or IPv6 routing, add `--no-proxy --ipv4`.
For realtime quotes, level-5 order books, tick trades, and stock pools, use Biying-backed `quote` commands. Provide Biying licences with `--licences` or `AMSTOCK_BIYING_LICENCES`.

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
```

Fetch event stock pools:

```powershell
uv run amstock quote pool --kind limit-up --date 2024-01-10 --licences licence1,licence2 --limit 20
```

## Mapping

- `stock list`: BaoStock `query_all_stock(day=...)`
- `stock basic`: BaoStock `query_stock_basic(code=...)`
- `sse-summary`: `ak.stock_sse_summary()`
- `szse-summary`: `ak.stock_szse_summary(date=...)`
- `quote stock/five/ticks/pool`: Biying API datasets

Treat source data as reference data, not investment advice.
