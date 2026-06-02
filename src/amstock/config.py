"""Application configuration primitives."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.engine import URL, make_url

from amstock.exceptions import ConfigurationError

DEFAULT_LANGUAGE = "zh-CN"
DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_STORE_ADMIN_TOKEN = "amstock-store-admin-token"
CLI_CONFIG_RELATIVE_PATH = Path("config") / "cli.toml"
DEFAULT_DATABASE_RELATIVE_PATH = Path("data") / "amstock.sqlite3"


@dataclass(frozen=True, slots=True)
class AppSettings:
    """Runtime settings shared by entry points and services."""

    database_url: str
    language: str = DEFAULT_LANGUAGE
    timezone: str = DEFAULT_TIMEZONE
    store_admin_token: str = DEFAULT_STORE_ADMIN_TOKEN


def amstock_root() -> Path:
    """Return the configured AMStock root directory."""

    value = os.environ.get("AMSTOCK_ROOT")
    if value is None or not value.strip():
        raise ConfigurationError("AMSTOCK_ROOT is required")
    root = Path(value).expanduser()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        msg = f"could not create AMSTOCK_ROOT: {root}"
        raise ConfigurationError(msg) from exc
    return root


def cli_config_path(root: Path | None = None) -> Path:
    """Return the CLI config file path for an AMStock root."""

    resolved_root = amstock_root() if root is None else root
    return resolved_root / CLI_CONFIG_RELATIVE_PATH


def default_database_url(root: Path | None = None) -> str:
    """Return the default SQLite database URL."""

    resolved_root = amstock_root() if root is None else root
    return sqlite_url_from_path(resolved_root / DEFAULT_DATABASE_RELATIVE_PATH)


def load_settings() -> AppSettings:
    """Load settings from AMSTOCK_ROOT/config/cli.toml."""

    root = amstock_root()
    config = load_cli_config(root)
    return AppSettings(
        database_url=resolve_database_url(root, config),
        language=get_nested_string(config, ("app", "language"), DEFAULT_LANGUAGE),
        timezone=get_nested_string(config, ("app", "timezone"), DEFAULT_TIMEZONE),
        store_admin_token=get_nested_string(
            config,
            ("store", "admin_token"),
            DEFAULT_STORE_ADMIN_TOKEN,
        ),
    )


def load_cli_config(root: Path) -> dict[str, Any]:
    """Load the required CLI TOML config."""

    config_path = cli_config_path(root)
    if not config_path.exists():
        msg = f"CLI config file is required: {config_path}"
        raise ConfigurationError(msg)
    try:
        with config_path.open("rb") as file:
            return tomllib.load(file)
    except tomllib.TOMLDecodeError as exc:
        msg = f"invalid CLI config TOML: {config_path}"
        raise ConfigurationError(msg) from exc
    except OSError as exc:
        msg = f"could not read CLI config file: {config_path}"
        raise ConfigurationError(msg) from exc


def resolve_database_url(root: Path, config: dict[str, Any]) -> str:
    """Resolve database settings, including root-relative SQLite paths."""

    database_config = get_nested_mapping(config, ("database",))
    path_value = database_config.get("path")
    if isinstance(path_value, str) and path_value.strip():
        return sqlite_url_from_path(resolve_root_relative_path(root, path_value))

    url_value = database_config.get("url")
    if isinstance(url_value, str) and url_value.strip():
        return resolve_sqlite_database_url(root, url_value)

    return default_database_url(root)


def resolve_sqlite_database_url(root: Path, database_url: str) -> str:
    """Resolve a SQLite URL's database path against AMSTOCK_ROOT when relative."""

    url = make_url(database_url)
    if url.drivername not in {"sqlite", "sqlite+pysqlite"}:
        return database_url
    if url.database in {None, "", ":memory:"}:
        return database_url

    database_path = Path(url.database).expanduser()
    if database_path.is_absolute():
        return database_url
    return str(URL.create(drivername=url.drivername, database=(root / database_path).as_posix()))


def sqlite_url_from_path(path: Path) -> str:
    """Build a SQLite URL from a filesystem path."""

    return str(URL.create(drivername="sqlite", database=path.expanduser().as_posix()))


def resolve_root_relative_path(root: Path, value: str) -> Path:
    """Resolve a path from TOML, using AMSTOCK_ROOT for relative values."""

    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return root / path


def get_nested_mapping(config: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    """Return a nested TOML mapping or an empty mapping."""

    current: object = config
    for key in keys:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    if not isinstance(current, dict):
        return {}
    return current


def get_nested_string(config: dict[str, Any], keys: tuple[str, ...], default: str) -> str:
    """Return a nested string setting."""

    current: object = config
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    if not isinstance(current, str) or not current.strip():
        return default
    return current
