"""Schedule K-1 parser — partner/shareholder income passthrough.

Handles K-1 from Form 1065 (partnership), 1120-S (S-corp), and 1041 (estate).
"""

from __future__ import annotations

import re
from typing import Optional

from wealthtax_agent.parsers.base import ParsedSlip

_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_ORD_INC_RE = re.compile(
    r"(?:box\s*1\b|ordinary\s+(?:business\s+)?income\s*(?:\(loss\))?).*?(-?\$[\d,]+\.?\d*)",
    re.IGNORECASE,
)
_NET_RENTAL_RE = re.compile(
    r"(?:box\s*2\b|net\s+rental\s+real\s+estate).*?(-?\$[\d,]+\.?\d*)", re.IGNORECASE
)
_INTEREST_RE = re.compile(
    r"(?:box\s*5\b|interest\s+income).*?\$([\d,]+\.?\d*)", re.IGNORECASE
)
_DIVIDENDS_RE = re.compile(
    r"(?:box\s*6[ab]?\b|ordinary\s+dividends?).*?\$([\d,]+\.?\d*)", re.IGNORECASE
)
_ST_CAP_RE = re.compile(
    r"(?:box\s*8\b|net\s+short[\s\-]?term\s+capital\s+gain).*?(-?\$[\d,]+\.?\d*)",
    re.IGNORECASE,
)
_LT_CAP_RE = re.compile(
    r"(?:box\s*9[ac]?\b|net\s+long[\s\-]?term\s+capital\s+gain).*?(-?\$[\d,]+\.?\d*)",
    re.IGNORECASE,
)
_ENTITY_RE = re.compile(r"(?:partnership|s[\s\-]?corp|estate|trust)\s+name[\s:]+([^\n]{3,60})", re.IGNORECASE)


def _money(m: Optional[re.Match]) -> Optional[float]:
    if m is None:
        return None
    return float(m.group(1).replace(",", "").replace("$", ""))


def parse_k1(text: str, source_filename: Optional[str] = None) -> ParsedSlip:
    fields: dict = {}
    text_fields: dict = {}

    year_m = _YEAR_RE.search(text)
    tax_year = int(year_m.group(1)) if year_m else None

    for key, pattern in [
        ("ordinary_business_income_loss", _ORD_INC_RE),
        ("net_rental_real_estate", _NET_RENTAL_RE),
        ("interest_income", _INTEREST_RE),
        ("ordinary_dividends", _DIVIDENDS_RE),
        ("net_short_term_capital_gain", _ST_CAP_RE),
        ("net_long_term_capital_gain", _LT_CAP_RE),
    ]:
        val = _money(pattern.search(text))
        if val is not None:
            fields[key] = val

    ent_m = _ENTITY_RE.search(text)
    if ent_m:
        text_fields["entity_name"] = ent_m.group(1).strip()

    # Distinguish entity type
    text_lower = text.lower()
    if "1065" in text or "partnership" in text_lower:
        text_fields["k1_type"] = "1065"
    elif "1120-s" in text_lower or "s corp" in text_lower:
        text_fields["k1_type"] = "1120-S"
    elif "1041" in text:
        text_fields["k1_type"] = "1041"

    confidence = "high" if len(fields) >= 2 else ("medium" if fields else "low")
    return ParsedSlip(
        jurisdiction="US",
        form_type="K-1",
        tax_year=tax_year,
        fields=fields,
        text_fields=text_fields,
        source_filename=source_filename,
        extractor="rule",
        confidence=confidence,
        raw_text=text,
    )
