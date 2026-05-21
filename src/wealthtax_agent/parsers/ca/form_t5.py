"""T5 parser — Statement of Investment Income."""

from __future__ import annotations

import re
from typing import Optional

from wealthtax_agent.parsers.base import ParsedSlip

_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_ELIGIBLE_DIV_RE = re.compile(
    r"(?:box\s*24|actual\s+amount\s+of\s+eligible\s+dividends?)[\s:]*\$?([\d,]+\.?\d*)",
    re.IGNORECASE,
)
_OTHER_DIV_RE = re.compile(
    r"(?:box\s*10|actual\s+amount\s+of\s+(?:other\s+)?dividends?)[\s:]*\$?([\d,]+\.?\d*)",
    re.IGNORECASE,
)
_INTEREST_RE = re.compile(
    r"(?:box\s*13|interest\s+from\s+cdn\s+sources)[\s:]*\$?([\d,]+\.?\d*)", re.IGNORECASE
)
_FOREIGN_INC_RE = re.compile(
    r"(?:box\s*15|foreign\s+income)[\s:]*\$?([\d,]+\.?\d*)", re.IGNORECASE
)
_FOREIGN_TAX_RE = re.compile(
    r"(?:box\s*16|foreign\s+tax\s+paid)[\s:]*\$?([\d,]+\.?\d*)", re.IGNORECASE
)


def _money(m: Optional[re.Match]) -> Optional[float]:
    if m is None:
        return None
    return float(m.group(1).replace(",", ""))


def parse_t5(text: str, source_filename: Optional[str] = None) -> ParsedSlip:
    fields: dict = {}
    text_fields: dict = {}

    year_m = _YEAR_RE.search(text)
    tax_year = int(year_m.group(1)) if year_m else None

    for key, pattern in [
        ("actual_amount_eligible_dividends", _ELIGIBLE_DIV_RE),
        ("actual_amount_other_dividends", _OTHER_DIV_RE),
        ("interest_cdn_sources", _INTEREST_RE),
        ("foreign_income", _FOREIGN_INC_RE),
        ("foreign_tax_paid", _FOREIGN_TAX_RE),
    ]:
        val = _money(pattern.search(text))
        if val is not None:
            fields[key] = val

    payer_m = re.search(r"payer['s]*\s+name[\s:]+([^\n]{3,60})", text, re.IGNORECASE)
    if payer_m:
        text_fields["payer_name"] = payer_m.group(1).strip()

    confidence = "high" if len(fields) >= 2 else ("medium" if fields else "low")
    return ParsedSlip(
        jurisdiction="CA",
        form_type="T5",
        tax_year=tax_year,
        fields=fields,
        text_fields=text_fields,
        source_filename=source_filename,
        extractor="rule",
        confidence=confidence,
        raw_text=text,
    )
