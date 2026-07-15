"""Tests for the sector-flow command-line interface."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from amstock import cli

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


GBK_SAMPLE = "\n".join(
    (
        "序 代码 名称 最新 涨幅% 主力净流入 集合竞价 超大单流入 超大单流出 超大单净额 超大单净占比 "
        "大单流入 大单流出 大单净额 大单净占比 中单流入 中单流出 中单净额 中单净占比 "
        "小单流入 小单流出 小单净额 小单净占比",
        "1 BK1106 创新药 1234.56 1.23 76.6亿 120万 80亿 3.4亿 76.6亿 12.3 20亿 8亿 12亿 4.5 "
        "5亿 6亿 -1亿 -2.0 3亿 4亿 -1亿 -1.5",
        "2 BK0477 航运港口 987.65 -0.45 -2355万 -30万 1亿 3000万 7000万 3.2 1.2亿 4500万 "
        "7500万 2.1 8000万 1亿 -2000万 -0.8 6000万 7000万 -1000万 -0.4",
    )
)


def test_sector_flow_cli_imports_and_lists_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unified commands persist parsed exports and filter their records."""

    configure_amstock_home(tmp_path, monkeypatch)
    flow_file = tmp_path / "flow.txt"
    flow_file.write_bytes(GBK_SAMPLE.encode("gbk"))

    imported = CliRunner().invoke(
        cli.app,
        ["sector-flow", "import", "--file", str(flow_file), "--date", "2026-07-15"],
    )
    listed = CliRunner().invoke(
        cli.app,
        ["sector-flow", "list", "--date", "2026-07-15", "--direction", "out"],
    )

    assert imported.exit_code == 0
    assert json.loads(imported.stdout)["count"] == 2
    assert listed.exit_code == 0
    assert json.loads(listed.stdout)["records"][0]["main_net_inflow_yuan"] == "-23550000"


def test_sector_flow_cli_returns_json_error_without_writing_invalid_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Invalid exports return JSON errors before the persistence service is created."""

    configure_amstock_home(tmp_path, monkeypatch)
    bad_file = tmp_path / "bad.txt"
    bad_file.write_text("bad header\nbad row", encoding="utf-8")

    result = CliRunner().invoke(cli.app, ["sector-flow", "import", "--file", str(bad_file)])

    assert result.exit_code == 1
    assert json.loads(result.stdout)["ok"] is False
    assert not (tmp_path / "data" / "store.sqlite3").exists()


def configure_amstock_home(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Create a sector-flow database config under a temporary AMSTOCK_HOME."""

    config_dir = root / "config"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        '[database]\npath = "data/store.sqlite3"\n', encoding="utf-8"
    )
    monkeypatch.setenv("AMSTOCK_HOME", str(root))
    monkeypatch.delenv("AMSTOCK_ROOT", raising=False)
