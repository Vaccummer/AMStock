---
name: amstock-sector
description: Fetch China A-share concept, industry, and sector relationship data through the unified AMStock CLI. Use when the user asks for market sectors, concept themes, industry boards, board rankings, leading sectors, board constituents, stocks inside a concept, or industry composition.
---

# AMStock Sector

Use `uv run amstock sector ...` from the AMStock project root. Commands emit JSON.
Use BaoStock for broad industry classification and Biying for concept/industry trees, stock membership, and stock-to-concept lookups. Provide Biying licences with `--licences` or `AMSTOCK_BIYING_LICENCES`.

Use `--limit` on broad lists. For `sector stocks`, pass the Biying index, industry, or concept code returned by `sector list --source biying`.

## Commands

List industry classifications or Biying concept tree:

```powershell
uv run amstock sector list --limit 30
uv run amstock sector list --source biying --licences licence1,licence2 --limit 30
```

List stocks in a Biying concept, industry, or index code:

```powershell
uv run amstock sector stocks --code sw_sysh --licences licence1,licence2 --limit 30
```

Find concepts, industries, and indices for one stock:

```powershell
uv run amstock sector concepts --symbol 000001 --licences licence1,licence2 --limit 30
```

Use the legacy AKShare skill script only when the user specifically needs Eastmoney board names or AKShare concept constituents that have not been promoted to the unified CLI:

```powershell
uv run python skills/amstock-sector/scripts/sector.py --kind concept-list --limit 30
uv run python skills/amstock-sector/scripts/sector.py --kind concept-cons --symbol 机器人概念 --limit 30
```

## Mapping

- `sector list`: BaoStock `query_stock_industry` by default
- `sector list --source biying`: Biying `concept-tree`
- `sector stocks`: Biying `concept-stocks`
- `sector concepts`: Biying `stock-concepts`
- Legacy script: AKShare `stock_board_concept_*_em` and `stock_board_industry_*_em`

Treat source data as reference data, not investment advice.
