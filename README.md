# AMStock

A Python application for stock market data workflows.

## Development

```powershell
uv sync
uv run ruff check .
uv run pytest
```

## Entry Points

```powershell
uv run amstock --help
uv run amstock --version
uv run amstock config init
uv run amstock config path
uv run amstock init-db
uv run amstock db init
uv run amstock stock basic --symbol 600519 --limit 5
uv run amstock stock profile --symbol 600519
uv run amstock stock history --symbol 600519 --start-date 20250101 --end-date 20250511 --adjust qfq --limit 20
uv run amstock quote batch --symbols 000063,600519
uv run amstock quote flow-summary --symbol 000063 --days 5
uv run amstock quote pool --kind limit-up --date 2024-01-10 --limit 20
uv run amstock quote all --source sina --limit 20
uv run amstock quote breadth
uv run amstock quote sentiment --date 2024-01-10
uv run amstock index quote --symbol 000001.SH
uv run amstock fund etf-list --limit 20
uv run amstock fund quote --symbol 159995
uv run amstock fund share-change --symbol 159995 --start-date 20260601 --end-date 20260605 --limit 5
uv run amstock us price --symbol NVDA
uv run amstock us quote --symbol AAPL
uv run amstock us quotes --symbols AAPL,MSFT,NVDA,GOOGL,META,AMZN,TSLA
uv run amstock us history --symbol NVDA --interval 1day --outputsize 30
uv run amstock us search --query nvidia
uv run amstock news gdelt --query "central bank" --country US --limit 10
uv run amstock news marketaux --query "oil sanctions" --symbols USO,CL=F --limit 10
uv run amstock news once
uv run amstock news server
uv run amstock news list --source gdelt-policy --query OPEC --limit 20
uv run amstock news queue
uv run amstock news replay --limit 50
uv run amstock portfolio summary --user alice --mark 600519=1580
uv run amstock sector-flow import --file /path/to/sector-flow.txt
uv run amstock sector-flow list --date 2026-07-15 --direction out --limit 30
uv run amstock sector-flow list --code BK1106
uv run amstock market-snapshot import --file /path/to/Table.txt --date 2026-07-15
uv run amstock market-snapshot list --date 2026-07-15 --industry 银行 --min-change 1 --sort-by change_percent --order desc --limit 30
uv run amstock sources capabilities
uv run amstock_src capabilities
```

CLI commands emit JSON so they can be used by scripts and agents.

`amstock` is the unified CLI. Use domain subcommands such as `stock`, `quote`,
`sector`, `index`, `fund`, and `portfolio` for day-to-day workflows. Use
`amstock sources ...` as the low-level data-source namespace.

`amstock_src` and `amstock_store` are kept as compatibility entry points. They
emit the same one-JSON-object command output and are still useful for existing
scripts.

## Configuration

AMStock reads configuration from `$AMSTOCK_HOME/config/config.toml`.
If `AMSTOCK_HOME` is not set, it defaults to `~/.amstock`.

Create a template config:

```powershell
uv run amstock config init
```

Example config:

```toml
[app]
language = "zh-CN"
timezone = "Asia/Shanghai"

[database]
path = "data/amstock.sqlite3"

[credentials.store]
admin_token = "amstock-store-admin-token"

[credentials.biying]
licences = ["licence1", "licence2"]
base_url = "https://api.biyingapi.com"
timeout = 20

[credentials.news]
gdelt_cloud_token = "gdelt-cloud-token"
marketaux_token = "marketaux-token"
gdelt_cloud_tokens = ["gdelt-cloud-token-1", "gdelt-cloud-token-2"]
marketaux_tokens = ["marketaux-token-1", "marketaux-token-2"]
proxy_url = "http://127.0.0.1:7897"

[credentials.twelvedata]
api_key = "twelvedata-api-key"
base_url = "https://api.twelvedata.com"
timeout = 20
proxy_url = "http://127.0.0.1:7897"

[news.server]
interval_seconds = 300
timezone = "Asia/Shanghai"
log_path = "logs/news_server.log"

[news.quiet_hours]
enabled = true
start = "23:00"
end = "08:30"
flush_on_end = true

[[news.sources]]
name = "eastmoney-flash"
type = "akshare_flash"
enabled = true
source = "eastmoney"
schedule_times = ["09:25", "09:30", "13:00", "15:05"]
active_windows = ["09:15-11:35", "12:55-15:10"]
limit = 100

[[news.sources]]
name = "sina-flash"
type = "akshare_flash"
enabled = true
source = "sina"
interval_seconds = 600
active_windows = ["09:15-11:35", "12:55-15:30"]
limit = 50

[[news.sources]]
name = "baidu-economic-calendar"
type = "akshare_economic_calendar"
enabled = true
schedule_times = ["07:30", "12:00", "18:00", "20:20"]
limit = 100

[[news.sources]]
name = "marketaux-us"
type = "marketaux"
enabled = true
symbols = "SPY,QQQ,NVDA,AAPL,GLD,USO"
language = "en"
limit = 20

[astrbot]
base_url = "http://localhost:6185"
api_key = "astrbot-api-key"
review_username = "amstock-news-agent"
review_session_id = "amstock-news-review"
timeout = 20

[[astrbot.subscribers]]
name = "main-user"
enabled = true
umo = "webchat:FriendMessage:openapi_probe"
min_importance = 4
markets = []
sources = ["eastmoney-flash", "marketaux-us"]
prompt_prefix = "Only push policy, macro, military, and market news that may affect investment decisions."
prompt_suffix = "Format message as final push-ready Chinese text with a clear first line and short bullet-like lines."
news_preference = "Focus on policy, macro, geopolitical, military, A-share, energy, FX/rates, and key industry events. Drop duplicate reports, opinion-only articles, soft PR, and low-impact items."
min_keep_importance = 2
realtime_min_importance = 5
realtime_min_urgency = 4
rating_batch_size = 30
digest_min_items = 10
digest_max_items = 40
digest_times = ["10:00", "12:00", "15:10", "20:30"]
review_session_id = "amstock-news-review-main-user"
max_context_chars = 12000

[astrbot.subscribers.quiet_hours]
enabled = true
start = "23:00"
end = "08:30"
flush_on_end = true
```

Relative paths, including `database.path`, are resolved from `AMSTOCK_HOME`.
`news.server.database_path` is optional; when omitted, news tables are created
in the shared SQLite database configured by `[database]`.
`news.server.log_path` controls where server cycle schedules and stats are
written as JSON Lines; relative paths are resolved from `AMSTOCK_HOME`.
Each source is scheduled through persisted `next_run_at` Unix epoch state. If
`schedule_times` is set, the next matching local time is used; otherwise the
source rolls forward by `interval_seconds`.
Use `active_windows` to restrict collection to local time ranges; sources that
become due outside those windows are deferred to the next window start.

News API tokens can also be passed per command with `--token` or read from
environment variables:

```powershell
$env:AMSTOCK_GDELT_CLOUD_TOKEN="gdelt-cloud-token"
$env:AMSTOCK_MARKETAUX_TOKEN="marketaux-token"
uv run amstock news gdelt --endpoint events --query "rate decision" --country US --from 2026-06-01 --to 2026-06-08 --limit 10
uv run amstock news marketaux --query "semiconductor export controls" --symbols NVDA,AMD --from 2026-06-01T00:00 --to 2026-06-08T23:59 --limit 10
```

Twelve Data credentials for US stock quote commands can also be supplied through
environment variables or per command:

```powershell
$env:AMSTOCK_TWELVEDATA_API_KEY="twelvedata-api-key"
$env:AMSTOCK_TWELVEDATA_PROXY="http://127.0.0.1:7897"
uv run amstock us price --symbol NVDA
uv run amstock us quote --symbol AAPL --proxy-url http://127.0.0.1:7897
uv run amstock us history --symbol MSFT --interval 1day --outputsize 20
```

The `us` commands use Twelve Data's REST API and emit one JSON object. API keys
are sent as query parameters to Twelve Data but are redacted from the returned
`url` metadata.

`news gdelt` is intended for global political, military, policy, and macro
event monitoring. `news marketaux` is intended for market and asset-linked
financial news. Both commands emit one JSON object for downstream agent
summarization, scoring, deduplication, and push delivery.

AKShare news sources support `akshare_flash` with `source = "eastmoney"`,
`"futu"`, `"sina"`, `"ths"`, or `"caixin"`. `akshare_economic_calendar`
collects Baidu macro calendar events for scheduled refreshes.

`news server` runs the push workflow: collect configured sources, dedupe news
in the shared SQLite database, parse each subscriber's natural-language
`news_preference` into structured features, then batch-rate new items through
AstrBot. The rating agent only extracts events, categories, `importance`, and
`urgency`; it does not write analysis. Items below `min_keep_importance` are
discarded. Items meeting `realtime_min_importance` and
`realtime_min_urgency` are pushed immediately. Other kept items enter the
digest cache and are summarized when `digest_min_items` is reached or a
configured `digest_times` time is hit. Non-urgent digest messages still obey
personal `quiet_hours` and can be sent later with `amstock news flush`.
Inspect quiet-hours delivery messages with `amstock news queue`. Reprocess
stored items with `amstock news replay --limit 50`; by default it skips items
that already have a successful sent delivery for the target subscriber.
Query stored news without side effects using `amstock news list`, with filters
such as `--source`, `--provider`, `--query`, `--since`, `--subscriber`,
`--review-push`, and `--delivery-status`.
Manage push recipients with:

```powershell
uv run amstock news subscriber list
uv run amstock news subscriber add --name qq-main --umo 2316:FriendMessage:E28EE73D29216FF05E466774984B2042 --sources eastmoney-flash,gdelt-policy
uv run amstock news subscriber pause qq-main
uv run amstock news subscriber resume qq-main
uv run amstock news subscriber sources qq-main --set eastmoney-flash,marketaux-market
```

The older `AMSTOCK_ROOT/config/cli.toml` path is still supported as a compatibility fallback.

Compatibility examples:

```powershell
uv run amstock_src price-history --symbol 600519 --start-date 20250101 --end-date 20250511 --adjust qfq --limit 20
uv run amstock_src financial-report --symbol 600519 --report-type income --limit 5 --no-proxy --ipv4
uv run amstock_src stock-basic --symbol 600519 --limit 5
uv run amstock_src industry-list --limit 20
```

### Biying source data

`amstock sources biying` fetches selected high-value datasets from Biying API. Do not
commit licences to the repository. Pass them per command or set
`AMSTOCK_BIYING_LICENCES` with comma, semicolon, or whitespace separated values,
or configure `[credentials.biying] licences = [...]` in `config.toml`.
When more than one licence is supplied, failed retryable HTTP requests try the
next licence. AMStock persists a lightweight rotation cursor under
`$AMSTOCK_HOME/data/biying_licence_rotation.json`; override
that path with `AMSTOCK_BIYING_ROTATION_FILE` if needed.

Examples:

```powershell
$env:AMSTOCK_BIYING_LICENCES="licence1,licence2"
uv run amstock stock concepts --symbol 000063 --limit 30
uv run amstock stock profile --symbol 000063
uv run amstock stock indexes --symbol 000063 --limit 20
uv run amstock stock indicators --symbol 000063 --st 20240601 --et 20240605 --limit 20
uv run amstock stock tech --symbol 000063 --indicator macd --period d --adjust n --lt 20
uv run amstock stock offering --symbol 000063 --limit 20
uv run amstock stock management --symbol 000063 --kind directors --limit 20
uv run amstock stock quarterly --symbol 000063 --kind profit --limit 20
uv run amstock quote batch --symbols 000063,600519,601991
uv run amstock quote all --source sina --limit 5000
uv run amstock quote all --source auto --limit 5000
uv run amstock quote flow-summary --symbol 000063 --days 5
uv run amstock quote intraday --symbol 000063 --period 1 --lt 240
uv run amstock quote history-intraday --symbol 000063 --date 20240605 --period 1 --lt 240
uv run amstock quote limit-price-history --symbol 000063 --st 20240601 --et 20240605
uv run amstock quote breadth
uv run amstock quote sentiment --date 2024-01-10
uv run amstock index intraday --symbol 000001.SH --period 1 --lt 240
uv run amstock index tech --symbol 000001.SH --indicator ma --period d --lt 20
uv run amstock fund quote --symbol 159995
uv run amstock fund share-change --symbol 159995 --start-date 20260601 --end-date 20260605 --limit 5
```

All-market realtime quotes should prefer `quote all --source sina`, backed by
AKShare Sina `stock_zh_a_spot`. The default `--source auto` tries the Biying
all-market endpoint first and falls back to Sina when Biying returns 429.
`quote breadth` and the breadth portion of `quote sentiment` use the same Sina
fallback.

`amstock_src biying` remains available as a compatibility entry point:

```powershell
uv run amstock_src biying --dataset limit-up-pool --date 2024-01-10 --limit 20
```

Run `uv run amstock sources capabilities` to inspect the full Biying dataset list.

Biying-backed unified commands now cover the high-value items from
`tmp/note.md`: company profile, stock concepts and indexes, stock pools,
multi-stock realtime quotes, market breadth, sentiment summary, stock flow
summary, intraday/history-intraday data, historical limit prices,
quote indicators, financial statements and quarterly data, shareholder data,
fund realtime quotes, index quotes, index intraday data, and stock/index
technical indicators.

The Biying HS documentation checked for this update did not expose direct
interfaces for sector capital-flow rankings, ETF holdings, ETF premium/IOPV,
margin financing, northbound holdings, index valuation
percentiles, sector valuation, LHB data, announcements/news, ETF PCF files, or
index futures/options IV. Those should be added later with another data source
instead of being faked through Biying.

ETF share-change is available through AKShare-backed `fund share-change`; pass
`--symbol` to infer the exchange and filter a single ETF, or pass `--exchange`
to fetch the exchange-level list.

Known unstable AKShare interfaces are routed directly to BaoStock in `amstock_src`
instead of trying AKShare first and falling back at runtime. Routing is fixed per
command, so a command returns a stable data schema instead of changing sources
after a runtime failure. Current direct BaoStock commands include `a-spot`,
`stock-basic`, `price-history`, and `industry-list`.

## Skills

AMStock includes agent skills that prefer the unified `amstock` CLI:

- `skills/amstock-market-quote`: A-share spot quotes, stock basics, exchange summaries, Biying order books, stock pools, market breadth, sentiment, index quotes, fund quotes, and ETF share-change.
- `skills/amstock-price-history`: A-share daily/weekly/monthly historical K-line data.
- `skills/amstock-fundamental`: A-share financial abstracts, statements, and Biying key indicators.
- `skills/amstock-sector`: A-share industry classification and Biying concept/sector relationships.
- `skills/amstock-news`: Global policy, military, macro, and market news for agent analysis and push workflows.
- `skills/amstock-store-user`: Configured database portfolio ledger workflows.
- `skills/amstock-store-admin`: Configured database portfolio user administration.
- `skills/amstock-portfolio-record`: Standalone JSON ledger for compatibility or isolated bookkeeping.

Example:

```powershell
uv run amstock stock history --symbol 600519 --start-date 20250101 --end-date 20250511 --adjust qfq --limit 20
```

BaoStock probes are also available while evaluating alternate data providers:

```powershell
uv run python scripts/baostock_login_probe.py
uv run python scripts/baostock_history.py --symbol 600000 --start-date 2024-01-02 --end-date 2024-01-10 --limit 5
uv run python scripts/baostock_stock_basic.py --symbol 600000
uv run python scripts/baostock_financial.py --kind profit --symbol 600000 --year 2023 --quarter 4
```

Local portfolio ledger example:

```powershell
uv run amstock portfolio trade buy --user alice --symbol 600519 --name 贵州茅台 --quantity 100 --price 1500 --fee 5
uv run amstock portfolio trade sell --user alice --symbol 600519 --quantity 40 --price 1600 --fee 5
uv run amstock portfolio trade delete --user alice --id 1
uv run amstock portfolio summary --user alice --mark 600519=1580
```
