---
name: amstock-sector
description: Fetch China A-share concept board and industry board data through AKShare. Use when the user asks for market sectors, concept themes, industry boards, board rankings, leading sectors, board constituents, stocks inside a concept, or industry composition.
---

# AMStock Sector

Use `scripts/sector.py` from the AMStock project root. The script emits JSON for concept and industry board lists or constituents.
If Eastmoney requests fail because of local proxy or IPv6 routing, add `--no-proxy --ipv4`.
If AKShare raises a connection error for `industry-list`, the script automatically falls back to BaoStock `query_stock_industry` and includes `fallback_from` in the JSON payload. BaoStock has no equivalent concept-board fallback.

Use `--limit` on board lists. For constituent queries, pass the board name exactly as AKShare expects it, usually the Chinese board name returned by the list command.

## Commands

List concept boards:

```powershell
uv run python skills/amstock-sector/scripts/sector.py --kind concept-list --limit 30
```

List stocks in a concept board:

```powershell
uv run python skills/amstock-sector/scripts/sector.py --kind concept-cons --symbol 机器人概念 --limit 30
```

List industry boards and constituents:

```powershell
uv run python skills/amstock-sector/scripts/sector.py --kind industry-list --limit 30
uv run python skills/amstock-sector/scripts/sector.py --kind industry-cons --symbol 小金属 --limit 30
```

## Mapping

- `concept-list`: `ak.stock_board_concept_name_em()`
- `concept-cons`: `ak.stock_board_concept_cons_em(symbol=...)`
- `industry-list`: `ak.stock_board_industry_name_em()`
- `industry-cons`: `ak.stock_board_industry_cons_em(symbol=...)`

BaoStock fallback:

- `industry-list`: `bs.query_stock_industry(code="", date="")`

Treat AKShare data as reference data, not investment advice.
