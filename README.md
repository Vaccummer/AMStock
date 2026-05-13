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
```

CLI commands emit JSON so they can be used by scripts and agents.

## Skills

AMStock includes agent skills that wrap focused AKShare interfaces:

- `skills/amstock-market-quote`: A-share spot quotes, stock basics, exchange summaries.
- `skills/amstock-price-history`: A-share daily/weekly/monthly historical K-line data.
- `skills/amstock-fundamental`: A-share financial abstracts and statements.
- `skills/amstock-sector`: A-share concept and industry board data.
- `skills/amstock-portfolio-record`: Local trade ledger, holdings, and return calculations.

Example:

```powershell
uv run python skills/amstock-price-history/scripts/price_history.py --symbol 600519 --start-date 20250101 --end-date 20250511 --adjust qfq --limit 20
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
uv run python skills/amstock-portfolio-record/scripts/portfolio_record.py record buy --symbol 600519 --name 贵州茅台 --quantity 100 --price 1500 --fee 5
uv run python skills/amstock-portfolio-record/scripts/portfolio_record.py record sell --symbol 600519 --quantity 40 --price 1600 --fee 5
uv run python skills/amstock-portfolio-record/scripts/portfolio_record.py summary --mark 600519=1580
```
