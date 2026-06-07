"""Tests for Biying API helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from amstock.biying_io import (
    BIYING_ENDPOINTS,
    biying_payload,
    build_biying_url,
    load_biying_licences,
    normalize_biying_market_symbol,
    normalize_biying_params,
    rotate_biying_licences,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_load_biying_licences_splits_common_separators() -> None:
    """Multiple licence values can be supplied in one option or environment value."""

    assert load_biying_licences("alpha,beta; gamma\nDelta") == [
        "alpha",
        "beta",
        "gamma",
        "Delta",
    ]


def test_load_biying_licences_requires_value(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing Biying licence fails before any HTTP request is attempted."""

    monkeypatch.delenv("AMSTOCK_BIYING_LICENCES", raising=False)
    monkeypatch.setenv("AMSTOCK_HOME", str(tmp_path))
    monkeypatch.delenv("AMSTOCK_ROOT", raising=False)

    with pytest.raises(ValueError, match="Biying licence is required"):
        load_biying_licences()


def test_load_biying_licences_reads_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Biying licences can be read from AMSTOCK_HOME/config/config.toml."""

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        """
[database]
path = "data/test.sqlite3"

[credentials.biying]
licences = ["alpha", "beta"]
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.delenv("AMSTOCK_BIYING_LICENCES", raising=False)
    monkeypatch.setenv("AMSTOCK_HOME", str(tmp_path))

    assert load_biying_licences() == ["alpha", "beta"]


def test_rotate_biying_licences_uses_configured_state_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Licence rotation persists the next starting slot."""

    state_file = tmp_path / "biying_rotation.json"
    monkeypatch.setenv("AMSTOCK_BIYING_ROTATION_FILE", str(state_file))

    assert rotate_biying_licences(["alpha", "beta", "gamma"]) == [
        "alpha",
        "beta",
        "gamma",
    ]
    assert rotate_biying_licences(["alpha", "beta", "gamma"]) == [
        "beta",
        "gamma",
        "alpha",
    ]


def test_build_biying_url_encodes_path_and_redacts_later() -> None:
    """Endpoint templates render encoded path parameters and query strings."""

    endpoint = BIYING_ENDPOINTS["sector-detail"]
    params = normalize_biying_params({"sector": "TFG板块趋势"})

    url = build_biying_url(endpoint, params=params, licence="lic-1")

    assert url == (
        "https://api.biyingapi.com/hslt/sectors/"
        "TFG%E6%9D%BF%E5%9D%97%E8%B6%8B%E5%8A%BF/lic-1"
    )


def test_build_biying_url_uses_default_base_url_for_all_market() -> None:
    """All-market endpoints avoid the legacy all-market subdomain certificate mismatch."""

    endpoint = BIYING_ENDPOINTS["stock-all-network"]

    url = build_biying_url(endpoint, params={}, licence="lic-1")

    assert url == "https://api.biyingapi.com/hsrl/real/all/lic-1"


def test_normalize_biying_market_symbol_infers_common_suffixes() -> None:
    """Stock symbols are normalized for endpoints that require market suffixes."""

    assert normalize_biying_market_symbol("600519") == "600519.SH"
    assert normalize_biying_market_symbol("000001") == "000001.SZ"
    assert normalize_biying_market_symbol("920000") == "920000.BJ"
    assert normalize_biying_market_symbol("000001.sz") == "000001.SZ"


def test_biying_payload_limits_tabular_records() -> None:
    """Biying list responses follow the AMStock JSON metadata contract."""

    endpoint = BIYING_ENDPOINTS["limit-up-pool"]
    payload = biying_payload(
        dataset="limit-up-pool",
        endpoint=endpoint,
        params={"date": "2024-01-10"},
        url="https://api.biyingapi.com/hslt/ztgc/2024-01-10/***",
        data=[
            {"dm": "sz000001", "mc": "平安银行"},
            {"dm": "sh600519", "mc": "贵州茅台"},
        ],
        limit=1,
        licence_count=2,
        attempted_urls=["https://api.biyingapi.com/hslt/ztgc/2024-01-10/***"],
    )

    assert payload["ok"] is True
    assert payload["source"] == "biying"
    assert payload["rows"] == 2
    assert payload["returned_rows"] == 1
    assert payload["columns"] == ["dm", "mc"]
    assert payload["data"] == [{"dm": "sz000001", "mc": "平安银行"}]
