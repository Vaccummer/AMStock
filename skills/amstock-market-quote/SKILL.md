---
name: amstock-market-quote
description: Fetch China A-share quotes, US stock quotes, market-wide spot data, exchange summaries, order book snapshots, stock pools, capital-flow summaries, market breadth, sentiment summaries, index quotes, fund quotes, and individual stock basics through the unified AMStock CLI. Use when the user asks for current A-share or US stock prices, quote snapshots, stock basic information, Shanghai/Shenzhen market summaries, broad market strength, short-term market mood, ETF realtime quotes, or wants to inspect a stock before deeper analysis.
---

# AMStock Market Quote

Use `uv run amstock ...` from the AMStock project root. Commands return one JSON object with `ok`, `function`, `params`, row counts, columns, and `data`.

Prefer `--limit` for broad datasets so the answer stays readable.
If Sina or other AKShare requests fail because of local proxy or IPv6 routing, add `--no-proxy --ipv4`.
For individual realtime quotes, level-5 order books, tick trades, stock pools, capital flow, index quotes, and fund quotes, use Biying-backed commands where available. Provide Biying licences with `--licences`, `AMSTOCK_BIYING_LICENCES`, or `[credentials.biying] licences = [...]` in `AMSTOCK_HOME/config/config.toml`.
For all-market realtime quotes, prefer `quote all --source sina`; the default `--source auto` tries Biying first and falls back to AKShare Sina if the Biying all-market endpoint returns 429.
For US stocks, use the Twelve Data-backed `us` commands. Provide the API key with `--api-key`, `AMSTOCK_TWELVEDATA_API_KEY`, or `[credentials.twelvedata] api_key = "..."` in `AMSTOCK_HOME/config/config.toml`. If outbound network access needs a proxy, use `--proxy-url`, `AMSTOCK_TWELVEDATA_PROXY`, or `[credentials.twelvedata] proxy_url = "http://127.0.0.1:7897"`.

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
```

Fetch all-market realtime quotes from AKShare Sina:

```powershell
uv run amstock quote all --source sina --limit 5000
uv run amstock quote all --source sina --limit 5000 --no-proxy --ipv4
uv run amstock quote all --source auto --licences licence1,licence2 --limit 5000
```

Fetch US stock quotes through Twelve Data:

```powershell
uv run amstock us price --symbol NVDA
uv run amstock us quote --symbol AAPL
uv run amstock us quotes --symbols AAPL,MSFT,NVDA,GOOGL,META,AMZN,TSLA
uv run amstock us history --symbol NVDA --interval 1day --outputsize 30
uv run amstock us search --query nvidia
uv run amstock us quote --symbol NVDA --proxy-url http://127.0.0.1:7897
```

Fetch event stock pools:

```powershell
uv run amstock quote pool --kind limit-up --date 2024-01-10 --licences licence1,licence2 --limit 20
uv run amstock quote pool --kind failed-limit-up --date 2024-01-10 --licences licence1,licence2 --limit 20
```

Summarize capital flow, market breadth, and short-term sentiment:

```powershell
uv run amstock quote flow-summary --symbol 000063 --days 5 --licences licence1,licence2
uv run amstock quote breadth --licences licence1,licence2 --no-proxy --ipv4
uv run amstock quote sentiment --date 2024-01-10 --licences licence1,licence2 --no-proxy --ipv4
```

Fetch index and fund realtime quotes:

```powershell
uv run amstock index quote --symbol 000001.SH --source auto --licences licence1,licence2
uv run amstock index quote --symbol 000001.SH --source akshare --no-proxy --ipv4
uv run amstock fund quote --symbol 159995 --licences licence1,licence2
```

Fetch ETF share-change data by symbol:

```powershell
uv run amstock fund share-change --symbol 159995 --start-date 20260601 --end-date 20260605 --limit 5
```

## Mapping

- `stock list`: BaoStock `query_all_stock(day=...)`
- `stock basic`: BaoStock `query_stock_basic(code=...)`
- `sse-summary`: `ak.stock_sse_summary()`
- `szse-summary`: `ak.stock_szse_summary(date=...)`
- `quote stock/five/ticks/batch/pool`: Biying API datasets
- `quote all --source sina`: AKShare Sina `stock_zh_a_spot`
- `quote all --source auto`: Biying all-market first, then AKShare Sina fallback on failure
- `quote flow-summary`: Biying `fund-flow` plus local AMStock aggregation
- `quote breadth`: Biying all-market realtime quotes plus local AMStock aggregation, with AKShare Sina fallback
- `quote sentiment`: Biying stock pools plus breadth aggregation, with AKShare Sina fallback for breadth
- `index quote --source auto`: Biying `index-realtime`, then AKShare index quote fallback
- `fund quote`: Biying `fund-realtime`
- `fund share-change --symbol`: AKShare ETF share-change source with exchange inference and symbol filtering
- `us price`: Twelve Data `/price`
- `us quote` and `us quotes`: Twelve Data `/quote`
- `us history`: Twelve Data `/time_series`
- `us search`: Twelve Data `/symbol_search`

Treat source data as reference data, not investment advice.
