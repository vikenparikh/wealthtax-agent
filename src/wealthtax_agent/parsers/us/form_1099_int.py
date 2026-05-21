"""1099-INT parser — interest income."""

from __future__ import annotations

import re
from typing import Optional

from wealthtax_agent.parsers.base import ParsedSlip

_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_INTEREST_RE = re.compile(
    r"(?:box\s*1|interest\s+income).*?\$([\d,]+\.?\d*)", re.IGNORECASE
)
_US_BOND_RE = re.compile(
    r"(?:box\s*3|interest\s+on\s+u\.?s\.?\s+savings).*?\$([\d,]+\.?\d*)", re.IGNORECASE
)
_FED_TAX_RE = re.compile(
    r"(?:box\s*4|federal\s+income\s+tax\s+withheld).*?\$([\d,]+\.?\d*)", re.IGNORECASE
)


def _money(m: Optional[re.Match]) -> Optional[float]:
    if m is None:
        return None
    return float(m.group(1).replace(",", "").replace("$", ""))


def parse_1099int(text: str, source_filename: Optional[str] = None) -> ParsedSlip:
    fields: dict = {}
    year_m = _YEAR_RE.search(text)
    tax_year = int(year_m.group(1)) if year_m else None

    for key, pattern in [
        ("interest_income", _INTEREST_RE),
        ("us_savings_bond_interest", _US_BOND_RE),
        ("federal_income_tax_withheld", _FED_TAX_RE),
    ]:
        val = _money(pattern.search(text))
        if val is not None:
            fields[key] = val

    confidence = "high" if fields else "low"
    return ParsedSlip(
        jurisdiction="US",
        form_type="1099-INT",
        tax_year=tax_year,
        fields=fields,
        source_filename=source_filename,
        extractor="rule",
        confidence=confidence,
        raw_text=text,
    )
