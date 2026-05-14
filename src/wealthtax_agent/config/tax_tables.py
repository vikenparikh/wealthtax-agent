"""Versioned tax tables loaded from YAML.

Layout:
    config/tax_tables/<jurisdiction>/<year>.yaml
    config/tax_tables/<jurisdiction>/<sub>/<region>/<year>.yaml

Example: config/tax_tables/ca/2024.yaml, config/tax_tables/ca/provinces/on/2024.yaml,
config/tax_tables/us/states/ca/2024.yaml.

Tables are pure data; the engines in ``engines/`` consume them.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


TABLES_ROOT = Path(__file__).resolve().parent / "tax_tables"


class MissingTableError(LookupError):
    pass


def _load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise MissingTableError(f"Tax table not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise MissingTableError(f"Tax table at {path} is not a mapping")
    return data


@lru_cache(maxsize=64)
def load_tables(jurisdiction: str, year: int, sub: Optional[str] = None, region: Optional[str] = None) -> Dict[str, Any]:
    """Load the federal table for a jurisdiction-year, or a sub-table.

    - ``load_tables("ca", 2024)`` -> federal CA table
    - ``load_tables("ca", 2024, sub="provinces", region="on")`` -> Ontario table
    - ``load_tables("us", 2024, sub="states", region="ca")`` -> California table
    """

    j = jurisdiction.lower()
    if sub and region:
        path = TABLES_ROOT / j / sub / region.lower() / f"{year}.yaml"
    else:
        path = TABLES_ROOT / j / f"{year}.yaml"
    return _load_yaml(path)


def available_years(jurisdiction: str) -> List[int]:
    j = jurisdiction.lower()
    root = TABLES_ROOT / j
    if not root.exists():
        return []
    years = []
    for child in root.iterdir():
        if child.is_file() and child.suffix == ".yaml":
            try:
                years.append(int(child.stem))
            except ValueError:
                continue
    return sorted(years)


def compute_progressive_tax(taxable_income: float, brackets: List[Dict[str, float]]) -> float:
    """Compute tax from a list of bracket dicts.

    Each bracket: {"up_to": <income ceiling or null for top>, "rate": <decimal>}.
    Brackets are evaluated lowest to highest; cumulative.
    """
    if taxable_income <= 0 or not brackets:
        return 0.0

    remaining = float(taxable_income)
    tax = 0.0
    lower = 0.0
    for bracket in brackets:
        rate = float(bracket.get("rate", 0.0))
        ceiling = bracket.get("up_to")
        if ceiling is None:
            tax += remaining * rate
            remaining = 0.0
            break
        ceiling = float(ceiling)
        width = max(0.0, ceiling - lower)
        if remaining <= width:
            tax += remaining * rate
            remaining = 0.0
            break
        tax += width * rate
        remaining -= width
        lower = ceiling
        if remaining <= 0:
            break
    return round(tax, 2)
