---
name: amstock-store-user
description: Record and query AMStock local store portfolio transactions, holdings, and returns. Use when the user wants to buy, sell, import opening positions, list trade history, view positions, or summarize realized and unrealized PnL. User-side commands do not require the admin token.
---

# AMStock Store User

Use `amstock_store` from the AMStock project root for local portfolio ledger workflows.
User-side commands do not require an admin token. A ledger user must already exist before
transactions can be recorded.

The store persists transaction records in the configured AMStock database and calculates
positions and returns from those records using FIFO cost accounting.
Configuration is loaded from `AMSTOCK_ROOT/config/cli.toml`; relative database paths are
resolved from `AMSTOCK_ROOT`.
`AMSTOCK_ROOT` must be set, and `config/cli.toml` must exist.

## Record Trades

Record a buy:

```powershell
uv run amstock_store trade buy --user alice --symbol 600519 --name 贵州茅台 --quantity 100 --price 1500 --fee 5 --date 2026-06-02 --note 加仓
```

Record a sell or reduction:

```powershell
uv run amstock_store trade sell --user alice --symbol 600519 --quantity 40 --price 1600 --fee 5 --date 2026-06-03 --note 减仓
```

Import an existing opening position:

```powershell
uv run amstock_store trade import-position --user alice --symbol 600519 --name 贵州茅台 --quantity 100 --avg-cost 1500 --date 2026-06-02
```

## Query Ledger

List transactions:

```powershell
uv run amstock_store trades --user alice
uv run amstock_store trades --user alice --symbol 600519 --limit 20
```

Calculate current positions:

```powershell
uv run amstock_store positions --user alice
uv run amstock_store positions --user alice --mark 600519=1580
```

Calculate portfolio summary:

```powershell
uv run amstock_store summary --user alice
uv run amstock_store summary --user alice --mark 600519=1580 --mark 000001=12.3
```

The CLI emits one JSON object. Sells that exceed current holdings are rejected.
