---
name: amstock-fundamental
description: Fetch China A-share fundamentals, financial statement data, and key indicators through the unified AMStock CLI. Use when the user asks about company fundamentals, financial abstracts, balance sheets, income statements, cash-flow statements, revenue, profit, assets, liabilities, or wants financial data for valuation and company analysis.
---

# AMStock Fundamental

Use `uv run amstock stock financial ...` from the AMStock project root. The command emits JSON and normalizes common six-digit A-share symbols.
If Eastmoney requests fail because of local proxy or IPv6 routing, add `--no-proxy --ipv4`.
For Biying financial ranges and per-share indicators, use `--source biying` and provide licences with `--licences` or `AMSTOCK_BIYING_LICENCES`.

## Commands

Fetch financial abstract data:

```powershell
uv run amstock stock financial --symbol 600519 --report-type abstract --limit 20
```

Fetch financial statements:

```powershell
uv run amstock stock financial --symbol 600519 --report-type balance --limit 20
uv run amstock stock financial --symbol 600519 --report-type income --limit 20
uv run amstock stock financial --symbol 600519 --report-type cash-flow --limit 20
```

Fetch Biying key indicators and date-ranged statements:

```powershell
uv run amstock stock financial --source biying --symbol 600519 --report-type pershareindex --st 20230101 --et 20251231 --licences licence1,licence2
uv run amstock stock financial --source biying --symbol 600519 --report-type balance --st 20230101 --et 20251231 --licences licence1,licence2
```

## Mapping

- `abstract`: AKShare `stock_financial_abstract(symbol=...)`
- `balance`: AKShare `stock_financial_report_sina(..., "资产负债表")` or Biying `financial-balance`
- `income`: AKShare `stock_financial_report_sina(..., "利润表")` or Biying `financial-income`
- `cash-flow`: AKShare `stock_financial_report_sina(..., "现金流量表")` or Biying `financial-cashflow`
- `pershareindex`: Biying `financial-pershareindex`

Treat source data as reference data, not investment advice.
