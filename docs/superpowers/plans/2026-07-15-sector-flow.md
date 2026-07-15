# 板块资金流导入与查询 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `amstock sector-flow import` and `list` commands that persist validated board-sector capital-flow TXT snapshots in SQLite.

**Architecture:** Parse and validate the whole text file into immutable Python records before opening a write transaction. A small SQLAlchemy model/repository/service stack persists date-and-sector upserts and queries them; a Typer command module exposes JSON-only CLI operations and is mounted in the unified CLI.

**Tech Stack:** Python 3.12, Typer, SQLAlchemy, SQLite, Decimal, pytest.

## Global Constraints

- Decode input by trying UTF-8, GB18030, then GBK; never infer the business date from the filename.
- Default `--date` to the actual execution date and accept an ISO `YYYY-MM-DD` override.
- Parse all rows to a Python intermediate table and validate them before any SQLite mutation.
- Store every monetary value as an exact `Decimal` count of yuan: `亿 * 100000000`, `万 * 10000`, preserving its sign.
- Table uniqueness is `(flow_date, sector_code)`; repeated import updates that row and does not remove rows absent from the new file.
- Keep the feature independent from the portfolio ledger and emit one JSON object per command.

---

### Task 1: Parse a sector-flow TXT into validated intermediate records

**Files:**
- Create: `src/amstock/sector_flow_io.py`
- Test: `tests/test_sector_flow_io.py`

**Interfaces:**
- Produces `SectorFlowInput` with `sector_code`, `sector_name`, `latest`, `change_percent`, `main_net_inflow_yuan`, `auction_yuan`, plus `super_order_inflow_yuan`, `super_order_outflow_yuan`, `super_order_net_yuan`, `super_order_net_ratio`, `large_order_inflow_yuan`, `large_order_outflow_yuan`, `large_order_net_yuan`, `large_order_net_ratio`, `medium_order_inflow_yuan`, `medium_order_outflow_yuan`, `medium_order_net_yuan`, `medium_order_net_ratio`, `small_order_inflow_yuan`, `small_order_outflow_yuan`, `small_order_net_yuan`, and `small_order_net_ratio`.
- Produces `parse_sector_flow_file(path: Path) -> list[SectorFlowInput]` and `parse_money_to_yuan(value: str, *, line_number: int) -> Decimal`.
- Raises `ValidationError` with the source line number when a required cell, number, or unit is invalid.

- [ ] **Step 1: Write failing parser tests**

```python
def test_parse_sector_flow_file_decodes_gbk_and_converts_money_units(tmp_path: Path) -> None:
    path = tmp_path / "flow.txt"
    path.write_bytes(GBK_SAMPLE.encode("gbk"))

    records = parse_sector_flow_file(path)

    assert records[0].sector_code == "BK1106"
    assert records[0].sector_name == "创新药"
    assert records[0].main_net_inflow_yuan == Decimal("7660000000")
    assert records[1].main_net_inflow_yuan == Decimal("-23550000")
    assert records[1].large_order_inflow_yuan == Decimal("120000000")


def test_parse_sector_flow_file_rejects_bad_amount_before_returning_records(tmp_path: Path) -> None:
    path = tmp_path / "flow.txt"
    path.write_text(GBK_SAMPLE.replace("76.6亿", "76.6千"), encoding="utf-8")

    with pytest.raises(ValidationError, match=r"line 2.*unknown money unit"):
        parse_sector_flow_file(path)
```

- [ ] **Step 2: Run the parser tests to verify they fail**

Run: `uv run pytest tests/test_sector_flow_io.py -v`

Expected: FAIL because `amstock.sector_flow_io` does not exist.

- [ ] **Step 3: Implement the pure parser**

```python
@dataclass(frozen=True, slots=True)
class SectorFlowInput:
    sector_code: str
    sector_name: str
    latest: Decimal
    change_percent: Decimal
    main_net_inflow_yuan: Decimal
    auction_yuan: Decimal
    super_order_inflow_yuan: Decimal
    super_order_outflow_yuan: Decimal
    super_order_net_yuan: Decimal
    super_order_net_ratio: Decimal
    large_order_inflow_yuan: Decimal
    large_order_outflow_yuan: Decimal
    large_order_net_yuan: Decimal
    large_order_net_ratio: Decimal
    medium_order_inflow_yuan: Decimal
    medium_order_outflow_yuan: Decimal
    medium_order_net_yuan: Decimal
    medium_order_net_ratio: Decimal
    small_order_inflow_yuan: Decimal
    small_order_outflow_yuan: Decimal
    small_order_net_yuan: Decimal
    small_order_net_ratio: Decimal


def parse_sector_flow_file(path: Path) -> list[SectorFlowInput]:
    text = _read_text(path)
    header, *rows = [line for line in text.splitlines() if line.strip()]
    columns = _header_positions(header)
    return [_parse_row(line, line_number=index, columns=columns)
            for index, line in enumerate(rows, start=2)]


def parse_money_to_yuan(value: str, *, line_number: int) -> Decimal:
    match = re.fullmatch(r"([+-]?\d+(?:\.\d+)?)(亿|万)", value.strip())
    if match is None:
        raise ValidationError(f"line {line_number}: unknown money unit: {value}")
    multiplier = Decimal("100000000") if match.group(2) == "亿" else Decimal("10000")
    return Decimal(match.group(1)) * multiplier
```

Use strict decode attempts in the required order. Split cells with `re.split(r"\s+", line.strip())`, map the 23 headings `序`、`代码`、`名称`、`最新`、`涨幅%`、`主力净流入`、`集合竞价` and the four 4-column order groups, parse `最新` and every net-ratio value with `Decimal`, and reject a duplicate sector code in one input file.

- [ ] **Step 4: Run the parser tests to verify they pass**

Run: `uv run pytest tests/test_sector_flow_io.py -v`

Expected: PASS with both conversion and malformed-unit tests passing.

- [ ] **Step 5: Commit the parser task**

```bash
git add src/amstock/sector_flow_io.py tests/test_sector_flow_io.py
git commit -m "feat: parse sector flow text files"
```

### Task 2: Persist and query dated sector-flow records

**Files:**
- Create: `src/amstock/models/sector_flow.py`
- Modify: `src/amstock/models/__init__.py`
- Create: `src/amstock/repositories/sector_flow.py`
- Create: `src/amstock/services/sector_flow.py`
- Test: `tests/test_sector_flow_service.py`

**Interfaces:**
- Consumes `list[SectorFlowInput]` from `parse_sector_flow_file`.
- Produces `SectorFlowService.import_records(*, flow_date: str, records: list[SectorFlowInput]) -> dict[str, object]` and `list_records(*, flow_date: str, sector_code: str | None, direction: Literal["in", "out"] | None, limit: int | None) -> dict[str, object]`.
- `SectorFlowRecord` maps `sector_flow_records` with a unique `(flow_date, sector_code)` constraint and `created_at`/`updated_at` audit columns.

- [ ] **Step 1: Write failing service tests**

```python
def test_import_upserts_same_date_and_lists_outflows_first() -> None:
    service = create_service()
    service.import_records(flow_date="2026-07-15", records=[record("BK1", "10万"), record("BK2", "-2亿")])
    service.import_records(flow_date="2026-07-15", records=[record("BK1", "-2355万")])

    result = service.list_records(
        flow_date="2026-07-15", sector_code=None, direction="out", limit=None
    )

    assert result["count"] == 2
    assert [item["sector_code"] for item in result["records"]] == ["BK2", "BK1"]
    assert result["records"][1]["main_net_inflow_yuan"] == "-23550000"
    assert result["records"][0]["main_net_inflow_display"] == "-2亿"


def test_import_does_not_write_when_validation_prevents_intermediate_table() -> None:
    service = create_service()
    with pytest.raises(ValidationError):
        service.import_records(flow_date="2026-07-15", records=[])
    assert service.list_records(flow_date="2026-07-15", sector_code=None, direction=None, limit=None)["count"] == 0
```

- [ ] **Step 2: Run service tests to verify they fail**

Run: `uv run pytest tests/test_sector_flow_service.py -v`

Expected: FAIL because the model, repository, and service do not exist.

- [ ] **Step 3: Implement model, repository, and service**

```python
class SectorFlowRecord(Base, EpochAuditMixin):
    __tablename__ = "sector_flow_records"
    __table_args__ = (UniqueConstraint("flow_date", "sector_code", name="uq_sector_flow_date_code"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    flow_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    sector_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    sector_name: Mapped[str] = mapped_column(String(128), nullable=False)
    main_net_inflow_yuan: Mapped[Decimal] = mapped_column(Numeric(28, 4), nullable=False)
    auction_yuan: Mapped[Decimal] = mapped_column(Numeric(28, 4), nullable=False)
    super_order_inflow_yuan: Mapped[Decimal] = mapped_column(Numeric(28, 4), nullable=False)
    super_order_outflow_yuan: Mapped[Decimal] = mapped_column(Numeric(28, 4), nullable=False)
    super_order_net_yuan: Mapped[Decimal] = mapped_column(Numeric(28, 4), nullable=False)
    super_order_net_ratio: Mapped[Decimal] = mapped_column(Numeric(28, 4), nullable=False)
    large_order_inflow_yuan: Mapped[Decimal] = mapped_column(Numeric(28, 4), nullable=False)
    large_order_outflow_yuan: Mapped[Decimal] = mapped_column(Numeric(28, 4), nullable=False)
    large_order_net_yuan: Mapped[Decimal] = mapped_column(Numeric(28, 4), nullable=False)
    large_order_net_ratio: Mapped[Decimal] = mapped_column(Numeric(28, 4), nullable=False)
    medium_order_inflow_yuan: Mapped[Decimal] = mapped_column(Numeric(28, 4), nullable=False)
    medium_order_outflow_yuan: Mapped[Decimal] = mapped_column(Numeric(28, 4), nullable=False)
    medium_order_net_yuan: Mapped[Decimal] = mapped_column(Numeric(28, 4), nullable=False)
    medium_order_net_ratio: Mapped[Decimal] = mapped_column(Numeric(28, 4), nullable=False)
    small_order_inflow_yuan: Mapped[Decimal] = mapped_column(Numeric(28, 4), nullable=False)
    small_order_outflow_yuan: Mapped[Decimal] = mapped_column(Numeric(28, 4), nullable=False)
    small_order_net_yuan: Mapped[Decimal] = mapped_column(Numeric(28, 4), nullable=False)
    small_order_net_ratio: Mapped[Decimal] = mapped_column(Numeric(28, 4), nullable=False)


def import_records(self, *, flow_date: str, records: list[SectorFlowInput]) -> dict[str, object]:
    normalized_date = validate_flow_date(flow_date)
    if not records:
        raise ValidationError("sector flow file contains no records")
    with self._database.session() as session:
        repository = SectorFlowRepository(session)
        written = repository.upsert_records(flow_date=normalized_date, records=records, now=self._clock.now_epoch())
        session.commit()
    return {"ok": True, "flow_date": normalized_date, "count": written}
```

Use repository lookup by `(flow_date, sector_code)` then update every snapshot field or add a new ORM record. Query with `main_net_inflow_yuan < 0` for `out`, `> 0` for `in`, order by `main_net_inflow_yuan.asc(), sector_code.asc()`, validate a positive limit, and serialize every amount as both a plain decimal yuan string and `format_money_yuan` output.

- [ ] **Step 4: Run service tests to verify they pass**

Run: `uv run pytest tests/test_sector_flow_service.py -v`

Expected: PASS with schema creation, upsert, direction filter, ordering, and JSON serialization verified.

- [ ] **Step 5: Commit the persistence task**

```bash
git add src/amstock/models/sector_flow.py src/amstock/models/__init__.py src/amstock/repositories/sector_flow.py src/amstock/services/sector_flow.py tests/test_sector_flow_service.py
git commit -m "feat: persist sector flow snapshots"
```

### Task 3: Expose the feature through the unified CLI and document it

**Files:**
- Create: `src/amstock/sector_flow_cli.py`
- Modify: `src/amstock/cli.py`
- Modify: `README.md`
- Test: `tests/test_sector_flow_cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes `parse_sector_flow_file`, `SectorFlowService`, and `create_application_context`.
- Produces `amstock sector-flow import --file PATH [--date YYYY-MM-DD]` and `amstock sector-flow list [--date YYYY-MM-DD] [--code CODE] [--direction in|out] [--limit N]`.

- [ ] **Step 1: Write failing CLI tests**

```python
def test_sector_flow_cli_imports_and_lists_records(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    configure_amstock_home(tmp_path, monkeypatch)
    flow_file = tmp_path / "flow.txt"
    flow_file.write_bytes(GBK_SAMPLE.encode("gbk"))

    imported = CliRunner().invoke(cli.app, ["sector-flow", "import", "--file", str(flow_file), "--date", "2026-07-15"])
    listed = CliRunner().invoke(cli.app, ["sector-flow", "list", "--date", "2026-07-15", "--direction", "out"])

    assert imported.exit_code == 0
    assert json.loads(imported.stdout)["count"] == 2
    assert listed.exit_code == 0
    assert json.loads(listed.stdout)["records"][0]["main_net_inflow_yuan"] == "-23550000"


def test_sector_flow_cli_returns_json_error_without_writing_invalid_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    configure_amstock_home(tmp_path, monkeypatch)
    bad_file = tmp_path / "bad.txt"
    bad_file.write_text("bad header\nbad row", encoding="utf-8")

    result = CliRunner().invoke(cli.app, ["sector-flow", "import", "--file", str(bad_file)])

    assert result.exit_code == 1
    assert json.loads(result.stdout)["ok"] is False
```

- [ ] **Step 2: Run CLI tests to verify they fail**

Run: `uv run pytest tests/test_sector_flow_cli.py -v`

Expected: FAIL because `sector-flow` is not mounted.

- [ ] **Step 3: Implement the Typer command module and mount it**

```python
@app.command("import")
def import_flow(
    file: Annotated[Path, typer.Option("--file", exists=True, readable=True)],
    flow_date: Annotated[str | None, typer.Option("--date")] = None,
) -> None:
    _run_json(lambda: _service().import_records(
        flow_date=validate_flow_date(flow_date), records=parse_sector_flow_file(file)
    ))


@app.command("list")
def list_flow(
    flow_date: Annotated[str | None, typer.Option("--date")] = None,
    code: Annotated[str | None, typer.Option("--code")] = None,
    direction: Annotated[Literal["in", "out"] | None, typer.Option("--direction")] = None,
    limit: Annotated[int | None, typer.Option("--limit")] = None,
) -> None:
    _run_json(lambda: _service().list_records(
        flow_date=validate_flow_date(flow_date), sector_code=code, direction=direction, limit=limit
    ))
```

Create schema inside `_service`, mirror `store_cli._run_json` error JSON behavior, import `app as sector_flow_app` in `cli.py`, and call `app.add_typer(sector_flow_app, name="sector-flow")`. Add the three documented CLI examples to README.

- [ ] **Step 4: Run CLI tests to verify they pass**

Run: `uv run pytest tests/test_sector_flow_cli.py tests/test_cli.py -v`

Expected: PASS with the command mounted and failed parsing returning JSON without records.

- [ ] **Step 5: Run full verification and commit**

Run: `uv run ruff check . && uv run pytest`

Expected: exit code 0 with no Ruff violations and all tests passing.

```bash
git add src/amstock/sector_flow_cli.py src/amstock/cli.py README.md tests/test_sector_flow_cli.py tests/test_cli.py
git commit -m "feat: add sector flow CLI"
```
