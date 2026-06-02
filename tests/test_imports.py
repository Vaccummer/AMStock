"""Import smoke tests for the project framework."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy.engine import make_url

from amstock.config import load_settings
from amstock.exceptions import ConfigurationError
from amstock.services import create_application_context

if TYPE_CHECKING:
    from pathlib import Path


def test_load_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings can be loaded without touching persistent storage."""

    configure_amstock_root(tmp_path, monkeypatch)
    settings = load_settings()

    assert settings.language
    assert settings.timezone


def test_load_settings_requires_amstock_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """AMSTOCK_ROOT is required for implicit settings loading."""

    monkeypatch.delenv("AMSTOCK_ROOT", raising=False)

    with pytest.raises(ConfigurationError, match="AMSTOCK_ROOT is required"):
        load_settings()


def test_load_settings_rejects_unusable_amstock_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AMSTOCK_ROOT must be creatable as a directory."""

    root_file = tmp_path / "not-a-directory"
    root_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("AMSTOCK_ROOT", str(root_file))

    with pytest.raises(ConfigurationError, match="could not create AMSTOCK_ROOT"):
        load_settings()


def test_load_settings_requires_cli_toml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The server CLI config file is required."""

    monkeypatch.setenv("AMSTOCK_ROOT", str(tmp_path))

    with pytest.raises(ConfigurationError, match="CLI config file is required"):
        load_settings()


def test_create_application_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Application context can be composed."""

    configure_amstock_root(tmp_path, monkeypatch)
    context = create_application_context()

    assert context.settings.database_url


def test_load_settings_from_amstock_root_cli_toml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Settings are loaded from AMSTOCK_ROOT/config/cli.toml."""

    configure_amstock_root(tmp_path, monkeypatch)

    settings = load_settings()
    database_url = make_url(settings.database_url)

    assert settings.store_admin_token == "server-token"
    assert database_url.database == (tmp_path / "data" / "server.sqlite3").as_posix()


def configure_amstock_root(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Create a CLI config under a temporary AMSTOCK_ROOT."""

    config_dir = root / "config"
    config_dir.mkdir()
    (config_dir / "cli.toml").write_text(
        """
[app]
language = "zh-CN"
timezone = "Asia/Shanghai"

[database]
path = "data/server.sqlite3"

[store]
admin_token = "server-token"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("AMSTOCK_ROOT", str(root))
