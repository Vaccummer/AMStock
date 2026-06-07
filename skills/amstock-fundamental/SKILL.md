---
name: amstock-fundamental
description: Fetch China A-share fundamentals, company profiles, financial statement data, quarterly data, shareholder data, governance member history, corporate actions, and key indicators through the unified AMStock CLI. Use when the user asks about company fundamentals, what a company does, financial abstracts, balance sheets, income statements, cash-flow statements, revenue, profit, assets, liabilities, holders, dividends, offerings, unlocks, or wants financial data for valuation and company analysis.
---

# AMStock Fundamental

Use `uv run amstock stock ...` from the AMStock project root. Commands emit JSON and normalize common six-digit A-share symbols.
If Eastmoney requests fail because of local proxy or IPv6 routing, add `--no-proxy --ipv4`.
For Biying financial ranges and per-share indicators, use `--source biying` and provide licences with `--licences`, `AMSTOCK_BIYING_LICENCES`, or `[credentials.biying] licences = [...]` in `AMSTOCK_HOME/config/config.toml`.

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
uv run amstock stock balance --symbol 600519 --st 20230101 --et 20251231 --licences licence1,licence2
uv run amstock stock income --symbol 600519 --st 20230101 --et 20251231 --licences licence1,licence2
uv run amstock stock cashflow --symbol 600519 --st 20230101 --et 20251231 --licences licence1,licence2
uv run amstock stock financial-summary --symbol 600519 --licences licence1,licence2
```

Fetch company profile, quarterly data, holders, and corporate actions:

```powershell
uv run amstock stock profile --symbol 600519 --licences licence1,licence2
uv run amstock stock quarterly --symbol 600519 --kind profit --licences licence1,licence2
uv run amstock stock quarterly --symbol 600519 --kind cashflow --licences licence1,licence2
uv run amstock stock holders --symbol 600519 --kind top --licences licence1,licence2
uv run amstock stock holders --symbol 600519 --kind float --licences licence1,licence2
uv run amstock stock holders --symbol 600519 --kind count --licences licence1,licence2
uv run amstock stock holders --symbol 600519 --kind fund --licences licence1,licence2
uv run amstock stock dividend --symbol 600519 --licences licence1,licence2
uv run amstock stock offering --symbol 600519 --licences licence1,licence2
uv run amstock stock unlock --symbol 600519 --licences licence1,licence2
uv run amstock stock management --symbol 600519 --kind directors --licences licence1,licence2
```

## Mapping

- `abstract`: AKShare `stock_financial_abstract(symbol=...)`
- `balance`: AKShare `stock_financial_report_sina(..., "资产负债表")` or Biying `financial-balance`
- `income`: AKShare `stock_financial_report_sina(..., "利润表")` or Biying `financial-income`
- `cash-flow`: AKShare `stock_financial_report_sina(..., "现金流量表")` or Biying `financial-cashflow`
- `pershareindex`: Biying `financial-pershareindex`
- `profile`: Biying `company-profile`
- `quarterly`: Biying `quarterly-profit` or `quarterly-cashflow`
- `holders`: Biying shareholder and fund-holding datasets
- `dividend/offering/unlock/management`: Biying corporate action and governance datasets

Treat source data as reference data, not investment advice.
