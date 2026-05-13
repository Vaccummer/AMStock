"""Smoke tests for bundled skill scripts."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_skill_scripts_expose_help() -> None:
    """Skill scripts can start without making AKShare network calls."""

    scripts = [
        PROJECT_ROOT / "skills/amstock-market-quote/scripts/market_quote.py",
        PROJECT_ROOT / "skills/amstock-price-history/scripts/price_history.py",
        PROJECT_ROOT / "skills/amstock-fundamental/scripts/fundamental.py",
        PROJECT_ROOT / "skills/amstock-sector/scripts/sector.py",
        PROJECT_ROOT / "scripts/baostock_login_probe.py",
        PROJECT_ROOT / "scripts/baostock_history.py",
        PROJECT_ROOT / "scripts/baostock_stock_basic.py",
        PROJECT_ROOT / "scripts/baostock_financial.py",
        PROJECT_ROOT / "skills/amstock-portfolio-record/scripts/portfolio_record.py",
    ]

    for script in scripts:
        result = subprocess.run(
            [sys.executable, str(script), "--help"],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert "usage:" in result.stdout
