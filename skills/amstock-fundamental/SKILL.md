---
name: amstock-fundamental
description: Fetch China A-share fundamentals and financial statement data through AKShare. Use when the user asks about company fundamentals, financial abstracts, balance sheets, income statements, cash-flow statements, revenue, profit, assets, liabilities, or wants financial data for valuation and company analysis.
---

# AMStock Fundamental

Use `scripts/fundamental.py` from the AMStock project root. The script emits JSON and normalizes common six-digit A-share symbols.
If Eastmoney requests fail because of local proxy or IPv6 routing, add `--no-proxy --ipv4`.
If AKShare raises a connection error and `--year --quarter` are provided, supported queries automatically fall back to BaoStock and include `fallback_from` in the JSON payload.

## Commands

Fetch financial abstract data:

```powershell
uv run python skills/amstock-fundamental/scripts/fundamental.py --kind abstract --symbol 600519 --limit 20
```

Fetch financial statements:

```powershell
uv run python skills/amstock-fundamental/scripts/fundamental.py --kind report --symbol 600519 --report-type balance --limit 20
uv run python skills/amstock-fundamental/scripts/fundamental.py --kind report --symbol 600519 --report-type income --limit 20
uv run python skills/amstock-fundamental/scripts/fundamental.py --kind report --symbol 600519 --report-type cash-flow --limit 20
```

## Mapping

- `abstract`: `ak.stock_financial_abstract(symbol=...)`
- `report --report-type balance`: `ak.stock_financial_report_sina(stock=..., symbol="资产负债表")`
- `report --report-type income`: `ak.stock_financial_report_sina(stock=..., symbol="利润表")`
- `report --report-type cash-flow`: `ak.stock_financial_report_sina(stock=..., symbol="现金流量表")`

BaoStock fallback:

- `abstract` and `income`: `bs.query_profit_data(code=..., year=..., quarter=...)`
- `balance`: `bs.query_balance_data(code=..., year=..., quarter=...)`
- `cash-flow`: `bs.query_cash_flow_data(code=..., year=..., quarter=...)`

Treat AKShare data as reference data, not investment advice.
