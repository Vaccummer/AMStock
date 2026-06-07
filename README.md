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
uv run amstock quote breadth
uv run amstock quote sentiment --date 2024-01-10
uv run amstock index quote --symbol 000001.SH
uv run amstock fund etf-list --limit 20
uv run amstock fund quote --symbol 159995
uv run amstock portfolio summary --user alice --mark 600519=1580
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
```

Relative paths, including `database.path`, are resolved from `AMSTOCK_HOME`.
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
uv run amstock quote all --feed network --limit 5000
uv run amstock quote flow-summary --symbol 000063 --days 5
uv run amstock quote intraday --symbol 000063 --period 1 --lt 240
uv run amstock quote history-intraday --symbol 000063 --date 20240605 --period 1 --lt 240
uv run amstock quote limit-price-history --symbol 000063 --st 20240601 --et 20240605
uv run amstock quote breadth
uv run amstock quote sentiment --date 2024-01-10
uv run amstock index intraday --symbol 000001.SH --period 1 --lt 240
uv run amstock index tech --symbol 000001.SH --indicator ma --period d --lt 20
uv run amstock fund quote --symbol 159995
```

`amstock_src biying` remains available as a compatibility entry point:

```powershell
uv run amstock_src biying --dataset limit-up-pool --date 2024-01-10 --limit 20
```

Run `uv run amstock sources capabilities` to inspect the full Biying dataset list.

Biying-backed unified commands now cover the high-value items from
`tmp/note.md`: company profile, stock concepts and indexes, stock pools,
multi-stock and all-market realtime quotes, market breadth, sentiment summary,
stock flow summary, intraday/history-intraday data, historical limit prices,
quote indicators, financial statements and quarterly data, shareholder data,
fund realtime quotes, index quotes, index intraday data, and stock/index
technical indicators.

The Biying HS documentation checked for this update did not expose direct
interfaces for sector capital-flow rankings, ETF holdings, ETF share-change,
ETF premium/IOPV, margin financing, northbound holdings, index valuation
percentiles, sector valuation, LHB data, announcements/news, ETF PCF files, or
index futures/options IV. Those should be added later with another data source
instead of being faked through Biying.

Known unstable AKShare interfaces are routed directly to BaoStock in `amstock_src`
instead of trying AKShare first and falling back at runtime. Routing is fixed per
command, so a command returns a stable data schema instead of changing sources
after a runtime failure. Current direct BaoStock commands include `a-spot`,
`stock-basic`, `price-history`, and `industry-list`.

## Skills

AMStock includes agent skills that prefer the unified `amstock` CLI:

- `skills/amstock-market-quote`: A-share spot quotes, stock basics, exchange summaries, Biying order books, and stock pools.
- `skills/amstock-price-history`: A-share daily/weekly/monthly historical K-line data.
- `skills/amstock-fundamental`: A-share financial abstracts, statements, and Biying key indicators.
- `skills/amstock-sector`: A-share industry classification and Biying concept/sector relationships.
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
uv run amstock portfolio summary --user alice --mark 600519=1580
```
