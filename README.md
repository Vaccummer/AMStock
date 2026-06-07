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
uv run amstock init-db
uv run amstock db init
uv run amstock stock basic --symbol 600519 --limit 5
uv run amstock stock history --symbol 600519 --start-date 20250101 --end-date 20250511 --adjust qfq --limit 20
uv run amstock quote pool --kind limit-up --date 2024-01-10 --limit 20
uv run amstock fund etf-list --limit 20
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
`AMSTOCK_BIYING_LICENCES` with comma, semicolon, or whitespace separated values.
When more than one licence is supplied, failed retryable HTTP requests try the
next licence. If `AMSTOCK_ROOT` is set, AMStock also persists a lightweight
rotation cursor under `AMSTOCK_ROOT/data/biying_licence_rotation.json`; override
that path with `AMSTOCK_BIYING_ROTATION_FILE` if needed.

Examples:

```powershell
$env:AMSTOCK_BIYING_LICENCES="licence1,licence2"
uv run amstock sources biying --dataset limit-up-pool --date 2024-01-10 --limit 20
uv run amstock sources biying --dataset stock-five --symbol 000001
uv run amstock sources biying --dataset stock-history --symbol 000001 --st 20240601 --et 20240605 --lt 20
uv run amstock sources biying --dataset fund-flow --symbol 000001 --st 20240601 --et 20240605 --lt 20
uv run amstock sources biying --dataset financial-pershareindex --symbol 600519 --st 20230101 --et 20251231
uv run amstock sources biying --dataset index-history --index 000001.SH --st 20240601 --et 20240605 --lt 20
```

`amstock_src biying` remains available as a compatibility entry point:

```powershell
uv run amstock_src biying --dataset limit-up-pool --date 2024-01-10 --limit 20
```

Run `uv run amstock sources capabilities` to inspect the full Biying dataset list.

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
