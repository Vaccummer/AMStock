"""Tests for the full-market snapshot command-line interface."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from amstock import cli

if TYPE_CHECKING:
    from pathlib import Path


HEADINGS = (
    "序 代码 名称 最新 涨幅% 涨跌 总量 现量 买入价 卖出价 涨速% 换手% 金额 "
    "市盈率(动) 所属行业 最高 最低 开盘 昨收 振幅% 量比 委比% 委差 均价 内盘 "
    "外盘 内外比 买一量 卖一量 市净率 总股本 总市值 流通股本 流通市值 3日涨幅% "
    "6日涨幅% 3日换手% 6日换手% 连涨天数 本月涨幅% 今年涨幅% 近一月涨幅% 近一年涨幅%"
)
ROW = (
    "1 300577 开润股份 20.36 19.98 3.39 1.04万 1.04万 20.36 — 0.00 0.73 "
    "2121万 12.36 服装家纺 20.36 20.36 20.36 16.97 0.00 107.08 100.00 "
    "27.9万 20.36 1.04万 0 1.00 27.9万 0 2.30 2.398亿 48.83亿 1.422亿 "
    "28.94亿 22.95 22.65 5.64 8.94 1 39.36 -3.55 33.95 2.67"
)


def test_import_uses_explicit_and_default_dates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_amstock_home(tmp_path, monkeypatch)
    source = tmp_path / "snapshot.txt"
    source.write_bytes(f"{HEADINGS}\n{ROW}\n".encode("gb18030"))
    runner = CliRunner()

    explicit = runner.invoke(
        cli.app,
        ["market-snapshot", "import", "--file", str(source), "--date", "2026-07-15"],
    )
    default = runner.invoke(
        cli.app, ["market-snapshot", "import", "--file", str(source)]
    )

    assert explicit.exit_code == 0
    assert json.loads(explicit.stdout) == {
        "inserted": 1,
        "ok": True,
        "rows_read": 1,
        "snapshot_date": "2026-07-15",
        "updated": 0,
    }
    assert default.exit_code == 0
    assert json.loads(default.stdout)["snapshot_date"] == date.today().isoformat()


def test_list_forwards_every_filter_to_service(monkeypatch: pytest.MonkeyPatch) -> None:
    import amstock.market_snapshot_cli as snapshot_cli

    captured: dict[str, object] = {}

    class FakeService:
        def list_records(self, **kwargs: object) -> dict[str, object]:
            captured.update(kwargs)
            return {"ok": True, "records": []}

    monkeypatch.setattr(snapshot_cli, "_service", lambda: FakeService())

    result = CliRunner().invoke(
        cli.app,
        [
            "market-snapshot",
            "list",
            "--date",
            "2026-07-15",
            "--code",
            "600519",
            "--name",
            "贵州",
            "--industry",
            "白酒",
            "--min-change",
            "-1.25",
            "--max-change",
            "9.5",
            "--min-turnover",
            "0.1",
            "--max-turnover",
            "12.3",
            "--min-pe",
            "5",
            "--max-pe",
            "40",
            "--min-market-cap",
            "100000000",
            "--max-market-cap",
            "999999999.99",
            "--sort-by",
            "change_percent",
            "--order",
            "desc",
            "--limit",
            "25",
        ],
    )

    assert result.exit_code == 0
    assert captured == {
        "snapshot_date": "2026-07-15",
        "code": "600519",
        "name": "贵州",
        "industry": "白酒",
        "min_change": Decimal("-1.25"),
        "max_change": Decimal("9.5"),
        "min_turnover": Decimal("0.1"),
        "max_turnover": Decimal("12.3"),
        "min_pe": Decimal("5"),
        "max_pe": Decimal("40"),
        "min_market_cap": Decimal("100000000"),
        "max_market_cap": Decimal("999999999.99"),
        "sort_by": "change_percent",
        "order": "desc",
        "limit": 25,
    }


@pytest.mark.parametrize(
    "arguments",
    (
        ["market-snapshot", "import", "--file", "/definitely/missing.txt"],
        ["market-snapshot", "list", "--date", "2026-02-30"],
        ["market-snapshot", "list", "--min-change", "many"],
        ["market-snapshot", "list", "--order", "sideways"],
        ["market-snapshot", "list", "--limit", "many"],
        ["market-snapshot", "list", "--limit", "0"],
    ),
)
def test_boundary_validation_errors_are_json(arguments: list[str]) -> None:
    result = CliRunner().invoke(cli.app, arguments)

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["type"]


def test_import_missing_file_is_one_json_error_without_stderr() -> None:
    result = CliRunner().invoke(cli.app, ["market-snapshot", "import"])

    assert result.exit_code == 1
    assert result.stderr == ""
    lines = result.stdout.splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload == {
        "error": {"message": "--file is required", "type": "ValidationError"},
        "ok": False,
    }


@pytest.mark.parametrize(
    "arguments",
    (
        ["market-snapshot", "import", "--unknown"],
        ["market-snapshot", "import", "--file"],
    ),
)
def test_import_usage_errors_are_one_json_error_without_stderr(
    arguments: list[str],
) -> None:
    result = CliRunner().invoke(cli.app, arguments)

    assert result.exit_code == 1
    assert result.stderr == ""
    lines = result.stdout.splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["ok"] is False
    assert payload["error"]["type"]
    assert payload["error"]["message"]


def test_market_snapshot_help_keeps_documented_import_options() -> None:
    result = CliRunner().invoke(
        cli.app, ["market-snapshot", "import", "--help"]
    )

    assert result.exit_code == 0
    assert "--file" in result.stdout
    assert "--date" in result.stdout
    assert result.stderr == ""


def test_market_snapshot_usage_normalization_is_feature_scoped() -> None:
    result = CliRunner().invoke(cli.app, ["sector-flow", "import", "--unknown"])

    assert result.exit_code == 2
    assert result.stdout == ""
    assert "No such option: --unknown" in result.stderr


def test_invalid_file_is_fully_parsed_before_database_is_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_amstock_home(tmp_path, monkeypatch)
    source = tmp_path / "bad.txt"
    source.write_text("bad header\nbad row\n", encoding="utf-8")

    result = CliRunner().invoke(
        cli.app, ["market-snapshot", "import", "--file", str(source)]
    )

    assert result.exit_code == 1
    assert json.loads(result.stdout)["ok"] is False
    assert not (tmp_path / "data" / "store.sqlite3").exists()


def test_shifted_row_is_rejected_before_database_is_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_amstock_home(tmp_path, monkeypatch)
    source = tmp_path / "shifted.txt"
    shifted_row = ROW.replace("12.36 服装家纺", "12.36 999 服装家纺", 1)
    source.write_bytes(f"{HEADINGS}\n{shifted_row}\n".encode("gb18030"))

    result = CliRunner().invoke(
        cli.app, ["market-snapshot", "import", "--file", str(source)]
    )

    assert result.exit_code == 1
    assert json.loads(result.stdout)["ok"] is False
    assert not (tmp_path / "data" / "store.sqlite3").exists()


def test_real_market_export_imports_all_5327_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_amstock_home(tmp_path, monkeypatch)

    result = CliRunner().invoke(
        cli.app,
        [
            "market-snapshot",
            "import",
            "--file",
            "/Users/am/External/tmp/Table.txt",
            "--date",
            "2026-07-15",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout)["rows_read"] == 5327


def configure_amstock_home(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_dir = root / "config"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        '[database]\npath = "data/store.sqlite3"\n', encoding="utf-8"
    )
    monkeypatch.setenv("AMSTOCK_HOME", str(root))
    monkeypatch.delenv("AMSTOCK_ROOT", raising=False)
