# Market Snapshot Final Fixes Report

## Outcome

Both final-review findings are fixed with regression coverage.

- Surplus-token stock-name recovery now validates every token selected for the
  reconstructed name. A token accepted by the snapshot numeric grammar, including
  scaled values and the nullable placeholder, rejects the row instead of shifting and
  silently corrupting later fields.
- Legitimate internal Chinese whitespace is still reconstructed; the focused test uses
  `五 粮 液` and expects `五粮液`.
- `market-snapshot import` accepts an optional value at the Typer boundary and validates
  `--file` inside `_run_json`, so omission emits exactly one JSON object on stdout, no
  stderr, and exit code 1.
- Importing the exact shifted-row anomaly is covered end to end and confirms parsing
  rejects the file before the SQLite database is created.
- `--file` is the only specifically required option in the market-snapshot command
  group. Framework-level unknown-option handling remains unchanged.

## TDD Evidence

The two new regressions were first run against the pre-fix implementation:

```text
uv run pytest -q tests/test_market_snapshot_io.py::test_parse_market_snapshot_rejects_later_surplus_numeric_token tests/test_market_snapshot_cli.py::test_import_missing_file_is_one_json_error_without_stderr
2 failed
```

The parser test reproduced the reviewer row with an extra `999` before industry and
observed that no exception was raised. The CLI test observed Typer exit 2 before the JSON
boundary.

After the minimal fixes, the regressions plus internal-space preservation passed:

```text
uv run pytest -q tests/test_market_snapshot_io.py::test_parse_market_snapshot_rejects_later_surplus_numeric_token tests/test_market_snapshot_io.py::test_parse_market_snapshot_joins_source_stock_name_with_internal_spaces tests/test_market_snapshot_cli.py::test_import_missing_file_is_one_json_error_without_stderr
3 passed
```

## Verification

Focused parser, CLI, service, and unified-CLI suites:

```text
uv run pytest -q tests/test_market_snapshot_io.py tests/test_market_snapshot_cli.py tests/test_market_snapshot_service.py tests/test_cli.py
82 passed in 2.42s
```

Ruff and independent real-export acceptance:

```text
uv run ruff check src/amstock/market_snapshot_io.py src/amstock/market_snapshot_cli.py tests/test_market_snapshot_io.py tests/test_market_snapshot_cli.py
All checks passed!

uv run pytest -q tests/test_market_snapshot_cli.py::test_real_market_export_imports_all_5327_rows
1 passed in 0.61s
```

Repository-wide suite:

```text
uv run pytest -q
169 passed, 2 failed in 3.18s
```

The two failures are pre-existing environment-sensitive tests unrelated to market
snapshots:

- `tests/test_imports.py::test_amstock_home_defaults_to_user_directory` sets Windows
  `USERPROFILE`, while macOS `Path.home()` remains `/Users/am`.
- `tests/test_twelvedata_io.py::test_time_series_counts_values` inherits configured proxy
  `http://127.0.0.1:7897`, while the test expects no proxy.

## Concerns

No market-snapshot blockers remain. The parser intentionally rejects a reconstructed
stock-name slice containing a numeric-only or scaled token; a future legitimate stock
name exported as a whitespace-separated numeric token would require an explicit format
rule rather than heuristic recovery.
