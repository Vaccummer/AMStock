# Sector Flow Final Fixes Report

## Outcome

All final-review findings were addressed without changing the public `sector-flow import`
or `sector-flow list` command names/options.

- Every sector-flow `Decimal` column now uses a focused SQLAlchemy `ExactDecimal`
  `TypeDecorator` backed by canonical SQLite `TEXT`; bind/result conversion never passes
  through binary floating point.
- Repository SQL only selects by date and optional sector code. Direction filtering,
  exact `Decimal` ordering with sector-code tie-breaking, and limiting run deterministically
  in Python.
- Typer accepts raw direction/limit strings and an unchecked `Path`; application validation
  happens inside `_run_json`, yielding stdout JSON and exit 1 for invalid direction,
  non-integer limit, and missing files.
- Parser headers reject duplicate and unknown columns with the physical header line number.
- Import results separately report `rows_read`, `inserted`, and `updated`.
- CLI tests cover omitted-date defaulting and exact `--code` filtering.

## Red-Green Evidence

Initial regression run:

```text
uv run pytest tests/test_sector_flow_service.py tests/test_sector_flow_io.py tests/test_sector_flow_cli.py -q
6 failed, 14 passed
```

The failures reproduced import-count ambiguity, SQLite large-decimal corruption, unknown and
duplicate header acceptance, missing import accounting, and Typer exit-2/non-JSON boundary
errors.

Canonical storage regression:

```text
uv run pytest tests/test_sector_flow_service.py::test_sqlite_round_trip_preserves_large_and_fractional_decimals_exactly -q
1 failed
```

The raw SQLite assertion showed `1.2300` rather than canonical `1.23`; the minimal bind
serializer fix made it green while retaining exact ORM values.

Final focused/adjacent verification:

```text
uv run pytest tests/test_sector_flow_service.py tests/test_sector_flow_io.py tests/test_sector_flow_cli.py tests/test_cli.py -q
56 passed
```

## Commits

- `6d70eee fix: harden sector flow persistence and validation`
- Documentation evidence is added by the immediately following report commit.

## Verification

```text
uv run ruff check .
All checks passed!

git diff --check
clean

uv run pytest -q
121 passed, 2 failed
```

The two full-suite failures are the user-authorized unrelated environment failures:

- `tests/test_imports.py::test_amstock_home_defaults_to_user_directory` uses `USERPROFILE`
  while macOS `Path.home()` resolves `/Users/am`.
- `tests/test_twelvedata_io.py::test_time_series_counts_values` inherits the configured
  `http://127.0.0.1:7897` proxy while the test expects no proxy.

## Concerns

SQLite `CREATE TABLE IF NOT EXISTS` does not migrate a sector-flow table created by a
pre-fix checkout from `NUMERIC` affinity to `TEXT`. Because this feature has not yet shipped,
fresh databases receive the correct schema; any developer database already containing the
experimental table should be recreated or explicitly migrated before relying on exact storage.
