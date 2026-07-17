# 全市场快照导入与查询 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `amstock market-snapshot import` and `list` commands for validated daily full-market TXT snapshots stored in SQLite.

**Architecture:** Decode and validate the complete 43-column export into immutable Python records before starting a write transaction. Store one wide typed snapshot row per `(snapshot_date, stock_code)` using lossless `ExactDecimal`, then apply SQL text filters and exact Python Decimal range/sort filters.

**Tech Stack:** Python 3.12, Typer, SQLAlchemy, SQLite, Decimal, pytest.

## Global Constraints

- Input format is `/Users/am/External/tmp/Table.txt`: GB18030/GBK or UTF-8, whitespace-delimited, 43 headings including `序`.
- Date defaults to local today, accepts strict `YYYY-MM-DD`, and never comes from the filename.
- Parse all nonblank rows into a Python intermediate table before opening the SQLite write transaction.
- Preserve leading-zero stock codes and treat source placeholder `—` as `None` for any numeric metric.
- Convert `万` and `亿` to the field's base unit with exact Decimal arithmetic; unitless values already use that base unit.
- Uniqueness is `(snapshot_date, stock_code)`; repeated import updates present codes and retains absent existing rows.
- CLI errors emit one JSON object on stdout with exit code 1.
- Query supports code, name, industry, change, turnover, PE and total-market-cap ranges, whitelist sorting, order and limit.

---

### Task 1: Parse the complete market snapshot export

**Files:**
- Create: `src/amstock/market_snapshot_io.py`
- Test: `tests/test_market_snapshot_io.py`

**Interfaces:**
- Produce frozen `MarketSnapshotInput` with `stock_code`, `stock_name`, `industry`, and typed fields for all remaining headings: `latest`, `change_percent`, `change_amount`, `total_volume`, `current_volume`, `bid_price`, `ask_price`, `speed_percent`, `turnover_percent`, `amount_yuan`, `dynamic_pe`, `high`, `low`, `open_price`, `previous_close`, `amplitude_percent`, `volume_ratio`, `order_ratio_percent`, `order_difference`, `average_price`, `inner_volume`, `outer_volume`, `inner_outer_ratio`, `bid_one_volume`, `ask_one_volume`, `pb`, `total_shares`, `total_market_cap_yuan`, `circulating_shares`, `circulating_market_cap_yuan`, `change_3d_percent`, `change_6d_percent`, `turnover_3d_percent`, `turnover_6d_percent`, `consecutive_up_days`, `month_change_percent`, `year_change_percent`, `one_month_change_percent`, `one_year_change_percent`.
- Produce `parse_market_snapshot_file(path: Path) -> list[MarketSnapshotInput]` and `parse_scaled_decimal(value: str, *, line_number: int, nullable: bool = False) -> Decimal | None`.

- [ ] **Step 1: Write failing parser tests**

Create a representative 2-row GB18030 fixture using the exact 43 headings. Assert `003001` remains a string, `1.04万` becomes `10400`, `2.398亿` becomes `239800000`, `—` becomes `None`, all named fields map correctly, and malformed units, duplicate codes, missing/unknown/duplicate headers report physical line numbers.

- [ ] **Step 2: Verify parser tests fail for the missing module**

Run: `uv run python -m pytest tests/test_market_snapshot_io.py -v`

Expected: collection fails with `ModuleNotFoundError: amstock.market_snapshot_io`.

- [ ] **Step 3: Implement the parser**

Use strict decoding order UTF-8, GB18030, GBK. Require exactly the heading tuple from the source file, split nonblank lines with `re.split(r"\s+", ...)`, parse finite Decimal values with optional `万`/`亿`, convert `—` to `None` for every numeric metric, and reject duplicate stock codes.

- [ ] **Step 4: Verify parser behavior**

Run: `uv run python -m pytest tests/test_market_snapshot_io.py -v && uv run ruff check src/amstock/market_snapshot_io.py tests/test_market_snapshot_io.py`

Expected: all parser tests pass and Ruff reports no errors.

- [ ] **Step 5: Commit parser**

```bash
git add src/amstock/market_snapshot_io.py tests/test_market_snapshot_io.py
git commit -m "feat: parse full market snapshot files"
```

### Task 2: Persist snapshots and implement exact queries

**Files:**
- Create: `src/amstock/models/market_snapshot.py`
- Modify: `src/amstock/models/__init__.py`
- Create: `src/amstock/repositories/market_snapshot.py`
- Create: `src/amstock/services/market_snapshot.py`
- Test: `tests/test_market_snapshot_service.py`

**Interfaces:**
- `MarketSnapshotRecord` maps every `MarketSnapshotInput` field plus ID, date and audit timestamps; every numeric source metric uses a nullable `ExactDecimal` column because the export may contain `—`.
- `MarketSnapshotService.import_records(snapshot_date: str, records: list[MarketSnapshotInput]) -> dict[str, object]` returns `rows_read`, `inserted`, `updated`.
- `MarketSnapshotService.list_records(...)` accepts text filters, Decimal range filters, `sort_by`, `order`, and `limit`, returning all fields as JSON-safe strings plus display values for amount/share/volume columns.

- [ ] **Step 1: Write failing persistence/query tests**

Test schema creation, 19-digit and 9-decimal lossless SQLite round trips, same-day upsert counts, retained absent rows, strict date rejection, exact code and name/industry filters, each numeric range family, ascending/descending whitelist sorting with code tie-break, default limit 100, invalid order/sort/limit, and no rows after empty-input validation.

- [ ] **Step 2: Verify service tests fail for missing modules**

Run: `uv run python -m pytest tests/test_market_snapshot_service.py -v`

Expected: collection fails because model/repository/service modules do not exist.

- [ ] **Step 3: Implement model, repository, and service**

Use a unique constraint named `uq_market_snapshot_date_code`. Repository upsert loads the date's existing codes once, adds or updates all fields, flushes once, and returns inserted/updated counts. Repository text filters use SQLite equality/contains; service applies Decimal ranges and sorting in Python to preserve exact numeric semantics.

- [ ] **Step 4: Verify persistence/query behavior**

Run: `uv run python -m pytest tests/test_market_snapshot_service.py tests/test_market_snapshot_io.py -v && uv run ruff check .`

Expected: focused tests and repository-wide Ruff pass.

- [ ] **Step 5: Commit persistence/query layer**

```bash
git add src/amstock/models/market_snapshot.py src/amstock/models/__init__.py src/amstock/repositories/market_snapshot.py src/amstock/services/market_snapshot.py tests/test_market_snapshot_service.py
git commit -m "feat: store and query market snapshots"
```

### Task 3: Add unified CLI and real-file acceptance coverage

**Files:**
- Create: `src/amstock/market_snapshot_cli.py`
- Modify: `src/amstock/cli.py`
- Modify: `README.md`
- Create: `tests/test_market_snapshot_cli.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- `amstock market-snapshot import --file PATH [--date YYYY-MM-DD]`.
- `amstock market-snapshot list` with `--date`, `--code`, `--name`, `--industry`, `--min-change`, `--max-change`, `--min-turnover`, `--max-turnover`, `--min-pe`, `--max-pe`, `--min-market-cap`, `--max-market-cap`, `--sort-by`, `--order`, `--limit`.

- [ ] **Step 1: Write failing CLI tests**

Test explicit/default date imports, all filters forwarded to service, JSON errors for invalid file/date/Decimal/order/limit, unified CLI mounting, and a real import of `/Users/am/External/tmp/Table.txt` into a temporary AMSTOCK_HOME asserting `rows_read == 5327`.

- [ ] **Step 2: Verify CLI tests fail before mounting**

Run: `uv run python -m pytest tests/test_market_snapshot_cli.py -v`

Expected: fails because `market-snapshot` is not a registered command.

- [ ] **Step 3: Implement and mount CLI**

Keep raw strings at the Typer boundary so validation occurs inside the JSON error wrapper. Parse the complete file before creating the service, mount `market_snapshot_app` in `src/amstock/cli.py`, and add import/query examples to README.

- [ ] **Step 4: Run focused and real-file verification**

Run: `uv run python -m pytest tests/test_market_snapshot_io.py tests/test_market_snapshot_service.py tests/test_market_snapshot_cli.py tests/test_cli.py -v && uv run ruff check .`

Expected: focused suites pass, real source imports 5,327 rows, and Ruff passes.

- [ ] **Step 5: Commit CLI and documentation**

```bash
git add src/amstock/market_snapshot_cli.py src/amstock/cli.py README.md tests/test_market_snapshot_cli.py tests/test_cli.py docs/superpowers/plans/2026-07-17-market-snapshot.md
git commit -m "feat: add full market snapshot CLI"
```
