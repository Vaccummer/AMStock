---
name: amstock-portfolio-record
description: Record local stock portfolio transactions and calculate returns. Use when the user wants to log holdings, buy records, sell or reduce-position records, review transaction history, calculate current position cost, realized profit/loss, unrealized profit/loss with mark prices, or summarize portfolio returns. Data is stored locally in this skill directory.
---

# AMStock Portfolio Record

Prefer `uv run amstock portfolio ...` for the configured AMStock database ledger.
Use `scripts/portfolio_record.py` only when the user explicitly wants this skill's standalone JSON ledger. The default data file is `skills/amstock-portfolio-record/data/portfolio.json`.

The script emits one JSON object. It uses FIFO cost accounting for sells and reduction records. This is a local bookkeeping tool, not tax, accounting, or investment advice.

Database ledger examples:

```powershell
uv run amstock portfolio trade buy --user alice --symbol 600519 --name 贵州茅台 --quantity 100 --price 1500 --fee 5 --date 2026-05-11
uv run amstock portfolio trade sell --user alice --symbol 600519 --quantity 40 --price 1600 --fee 5 --date 2026-05-12 --note 减仓
uv run amstock portfolio trades --user alice --symbol 600519 --limit 10
uv run amstock portfolio positions --user alice --mark 600519=1580
uv run amstock portfolio summary --user alice --mark 600519=1580
```

## Record Trades

Standalone JSON ledger: record a buy:

```powershell
uv run python skills/amstock-portfolio-record/scripts/portfolio_record.py record buy --symbol 600519 --name 贵州茅台 --quantity 100 --price 1500 --fee 5 --date 2026-05-11
```

Standalone JSON ledger: record a sell or reduction:

```powershell
uv run python skills/amstock-portfolio-record/scripts/portfolio_record.py record sell --symbol 600519 --quantity 40 --price 1600 --fee 5 --date 2026-05-12 --note 减仓
```

## Query Ledger

List transaction history:

```powershell
uv run python skills/amstock-portfolio-record/scripts/portfolio_record.py trades
uv run python skills/amstock-portfolio-record/scripts/portfolio_record.py trades --symbol 600519 --limit 10
```

Calculate positions:

```powershell
uv run python skills/amstock-portfolio-record/scripts/portfolio_record.py positions
uv run python skills/amstock-portfolio-record/scripts/portfolio_record.py positions --mark 600519=1580
```

Calculate portfolio summary:

```powershell
uv run python skills/amstock-portfolio-record/scripts/portfolio_record.py summary --mark 600519=1580
```

## Storage

- Default store: `skills/amstock-portfolio-record/data/portfolio.json`
- Use `--store <path>` for tests or alternate ledgers.
- Use `reset` only when the user explicitly asks to clear the local ledger.
