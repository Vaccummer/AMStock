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
AMSTOCK_HOME_ENV = "AMSTOCK_HOME"
AMSTOCK_LEGACY_ROOT_ENV = "AMSTOCK_ROOT"
CONFIG_RELATIVE_PATH = Path("config") / "config.toml"
LEGACY_CLI_CONFIG_RELATIVE_PATH = Path("config") / "cli.toml"
DEFAULT_DATABASE_RELATIVE_PATH = Path("data") / "amstock.sqlite3"


@dataclass(frozen=True, slots=True)
class AppSettings:
    """Runtime settings shared by entry points and services."""

    database_url: str
    language: str = DEFAULT_LANGUAGE
    timezone: str = DEFAULT_TIMEZONE
    store_admin_token: str = DEFAULT_STORE_ADMIN_TOKEN
    biying_licences: tuple[str, ...] = ()
    biying_base_url: str = "https://api.biyingapi.com"
    biying_timeout: float = 20.0


def default_config_toml() -> str:
    """Return a default AMStock config template."""

    return """
[app]
language = "zh-CN"
timezone = "Asia/Shanghai"

[database]
path = "data/amstock.sqlite3"

[credentials.store]
admin_token = "amstock-store-admin-token"

[credentials.biying]
licences = []
base_url = "https://api.biyingapi.com"
timeout = 20
""".strip() + "\n"


def amstock_home() -> Path:
    """Return the configured AMStock home directory."""

    value = os.environ.get(AMSTOCK_HOME_ENV)
    if value is None or not value.strip():
        value = "~/.amstock"
    home = Path(value).expanduser()
    try:
        home.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        msg = f"could not create {AMSTOCK_HOME_ENV}: {home}"
        raise ConfigurationError(msg) from exc
    return home


def amstock_root() -> Path:
    """Return the configured AMStock root directory.

    Kept for compatibility with older code; new configuration uses AMSTOCK_HOME.
    """

    return amstock_home()


def legacy_amstock_root() -> Path | None:
    """Return the legacy AMSTOCK_ROOT directory when explicitly configured."""

    value = os.environ.get(AMSTOCK_LEGACY_ROOT_ENV)
    if value is None or not value.strip():
        return None
    root = Path(value).expanduser()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        msg = f"could not create {AMSTOCK_LEGACY_ROOT_ENV}: {root}"
        raise ConfigurationError(msg) from exc
    return root


def config_path(home: Path | None = None) -> Path:
    """Return the primary config file path for an AMStock home."""

    resolved_home = amstock_home() if home is None else home
    return resolved_home / CONFIG_RELATIVE_PATH


def cli_config_path(root: Path | None = None) -> Path:
    """Return the legacy CLI config file path."""

    resolved_root = amstock_home() if root is None else root
    return resolved_root / LEGACY_CLI_CONFIG_RELATIVE_PATH


def default_database_url(home: Path | None = None) -> str:
    """Return the default SQLite database URL."""

    resolved_home = amstock_home() if home is None else home
    return sqlite_url_from_path(resolved_home / DEFAULT_DATABASE_RELATIVE_PATH)


def load_settings() -> AppSettings:
    """Load settings from AMSTOCK_HOME/config/config.toml."""

    home = amstock_home()
    path = resolve_config_path(home)
    config = load_config_file(path)
    config_root = path.parent.parent
    return AppSettings(
        database_url=resolve_database_url(config_root, config),
        language=get_nested_string(config, ("app", "language"), DEFAULT_LANGUAGE),
        timezone=get_nested_string(config, ("app", "timezone"), DEFAULT_TIMEZONE),
        store_admin_token=resolve_store_admin_token(config),
        biying_licences=resolve_biying_licences(config),
        biying_base_url=get_nested_string(
            config,
            ("credentials", "biying", "base_url"),
            "https://api.biyingapi.com",
        ),
        biying_timeout=get_nested_float(config, ("credentials", "biying", "timeout"), 20.0),
    )


def load_cli_config(root: Path) -> dict[str, Any]:
    """Load a legacy CLI TOML config."""

    return load_config_file(cli_config_path(root))


def resolve_config_path(home: Path) -> Path:
    """Return the first available config path, preferring the new location."""

    primary = config_path(home)
    if primary.exists():
        return primary

    legacy_under_home = cli_config_path(home)
    if legacy_under_home.exists():
        return legacy_under_home

    legacy_root = legacy_amstock_root()
    if legacy_root is not None:
        legacy_path = cli_config_path(legacy_root)
        if legacy_path.exists():
            return legacy_path

    msg = f"config file is required: {primary}"
    raise ConfigurationError(msg)


def load_config_file(path: Path) -> dict[str, Any]:
    """Load a TOML config file."""

    if not path.exists():
        msg = f"config file is required: {path}"
        raise ConfigurationError(msg)
    try:
        with path.open("rb") as file:
            return tomllib.load(file)
    except tomllib.TOMLDecodeError as exc:
        msg = f"invalid config TOML: {path}"
        raise ConfigurationError(msg) from exc
    except OSError as exc:
        msg = f"could not read config file: {path}"
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
    """Resolve a SQLite URL's database path against AMSTOCK_HOME when relative."""

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
    """Resolve a path from TOML, using AMSTOCK_HOME for relative values."""

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


def get_nested_float(config: dict[str, Any], keys: tuple[str, ...], default: float) -> float:
    """Return a nested float setting."""

    current: object = config
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    if isinstance(current, int | float):
        return float(current)
    if isinstance(current, str) and current.strip():
        try:
            return float(current)
        except ValueError:
            return default
    return default


def resolve_store_admin_token(config: dict[str, Any]) -> str:
    """Resolve the local store admin token from new or legacy config sections."""

    token = get_nested_string(config, ("credentials", "store", "admin_token"), "")
    if token:
        return token
    return get_nested_string(config, ("store", "admin_token"), DEFAULT_STORE_ADMIN_TOKEN)


def resolve_biying_licences(config: dict[str, Any]) -> tuple[str, ...]:
    """Resolve Biying licences from config."""

    credentials = get_nested_mapping(config, ("credentials", "biying"))
    licences = credentials.get("licences")
    if isinstance(licences, list):
        return tuple(str(item).strip() for item in licences if str(item).strip())

    licence = credentials.get("licence")
    if isinstance(licence, str) and licence.strip():
        return (licence.strip(),)

    legacy = get_nested_string(config, ("biying", "licences"), "")
    if legacy:
        return tuple(item.strip() for item in legacy.replace(";", ",").split(",") if item.strip())

    return ()
