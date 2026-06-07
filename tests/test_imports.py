"""Import smoke tests for the project framework."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy.engine import make_url

from amstock.config import amstock_home, config_path, load_settings
from amstock.exceptions import ConfigurationError
from amstock.services import create_application_context

if TYPE_CHECKING:
    from pathlib import Path


def test_load_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings can be loaded without touching persistent storage."""

    configure_amstock_home(tmp_path, monkeypatch)
    settings = load_settings()

    assert settings.language
    assert settings.timezone


def test_amstock_home_defaults_to_user_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AMSTOCK_HOME defaults to ~/.amstock."""

    monkeypatch.delenv("AMSTOCK_HOME", raising=False)
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    assert amstock_home() == tmp_path / ".amstock"


def test_load_settings_rejects_unusable_amstock_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AMSTOCK_HOME must be creatable as a directory."""

    root_file = tmp_path / "not-a-directory"
    root_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("AMSTOCK_HOME", str(root_file))

    with pytest.raises(ConfigurationError, match="could not create AMSTOCK_HOME"):
        load_settings()


def test_load_settings_requires_config_toml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The config file is required."""

    monkeypatch.setenv("AMSTOCK_HOME", str(tmp_path))

    with pytest.raises(ConfigurationError, match="config file is required"):
        load_settings()


def test_create_application_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Application context can be composed."""

    configure_amstock_home(tmp_path, monkeypatch)
    context = create_application_context()

    assert context.settings.database_url


def test_load_settings_from_amstock_home_config_toml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Settings are loaded from AMSTOCK_HOME/config/config.toml."""

    configure_amstock_home(tmp_path, monkeypatch)

    settings = load_settings()
    database_url = make_url(settings.database_url)

    assert settings.store_admin_token == "server-token"
    assert settings.biying_licences == ("lic-a", "lic-b")
    assert database_url.database == (tmp_path / "data" / "server.sqlite3").as_posix()
    assert config_path(tmp_path) == tmp_path / "config" / "config.toml"


def test_load_settings_from_legacy_amstock_root_cli_toml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy AMSTOCK_ROOT/config/cli.toml remains supported."""

    configure_legacy_amstock_root(tmp_path, monkeypatch)

    settings = load_settings()
    database_url = make_url(settings.database_url)

    assert settings.store_admin_token == "legacy-token"
    assert database_url.database == (tmp_path / "data" / "legacy.sqlite3").as_posix()


def configure_amstock_home(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Create a config under a temporary AMSTOCK_HOME."""

    config_dir = root / "config"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        """
[app]
language = "zh-CN"
timezone = "Asia/Shanghai"

[database]
path = "data/server.sqlite3"

[credentials.store]
admin_token = "server-token"

[credentials.biying]
licences = ["lic-a", "lic-b"]
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("AMSTOCK_HOME", str(root))
    monkeypatch.delenv("AMSTOCK_ROOT", raising=False)


def configure_legacy_amstock_root(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Create a legacy CLI config under a temporary AMSTOCK_ROOT."""

    config_dir = root / "config"
    config_dir.mkdir()
    (config_dir / "cli.toml").write_text(
        """
[database]
path = "data/legacy.sqlite3"

[store]
admin_token = "legacy-token"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("AMSTOCK_HOME", str(root / "missing-home"))
    monkeypatch.setenv("AMSTOCK_ROOT", str(root))
