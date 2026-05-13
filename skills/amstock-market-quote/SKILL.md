---
name: amstock-market-quote
description: Fetch China A-share real-time quotes, market-wide spot data, exchange summaries, and individual stock basics through AKShare. Use when the user asks for current A-share prices, quote snapshots, stock basic information, Shanghai/Shenzhen market summaries, or wants to inspect a stock before deeper analysis.
---

# AMStock Market Quote

Use `scripts/market_quote.py` from the AMStock project root. The script returns one JSON object with `ok`, `function`, `params`, row counts, columns, and `data`.

Prefer `--limit` for broad datasets so the answer stays readable.
If Eastmoney requests fail because of local proxy or IPv6 routing, add `--no-proxy --ipv4`.
If AKShare raises a connection error, supported queries automatically fall back to BaoStock and include `fallback_from` in the JSON payload.

## Commands

Fetch all A-share spot quotes:

```powershell
uv run python skills/amstock-market-quote/scripts/market_quote.py --kind a-spot --limit 20
```

Fetch individual stock basics:

```powershell
uv run python skills/amstock-market-quote/scripts/market_quote.py --kind individual --symbol 600519
uv run python skills/amstock-market-quote/scripts/market_quote.py --kind individual --symbol 600519 --no-proxy --ipv4
```

Fetch exchange summaries:

```powershell
uv run python skills/amstock-market-quote/scripts/market_quote.py --kind sse-summary
uv run python skills/amstock-market-quote/scripts/market_quote.py --kind szse-summary --date 20240830
```

## Mapping

- `a-spot`: `ak.stock_zh_a_spot_em()`
- `individual`: `ak.stock_individual_info_em(symbol=...)`
- `sse-summary`: `ak.stock_sse_summary()`
- `szse-summary`: `ak.stock_szse_summary(date=...)`

BaoStock fallback:

- `a-spot`: `bs.query_all_stock(day=...)`
- `individual`: `bs.query_stock_basic(code=...)`

Treat AKShare data as reference data, not investment advice.
