"""W-2 parser — wages, tips, and other compensation."""

from __future__ import annotations

import re
from typing import Optional

from wealthtax_agent.parsers.base import ParsedSlip

_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_WAGES_RE = re.compile(
    r"(?:box\s*1\b|wages,?\s+tips).*?\$([\d,]+\.?\d*)", re.IGNORECASE
)
_FED_TAX_RE = re.compile(
    r"(?:box\s*2\b|federal\s+income\s+tax\s+withheld).*?\$([\d,]+\.?\d*)", re.IGNORECASE
)
_SS_WAGES_RE = re.compile(
    r"(?:box\s*3\b|social\s+security\s+wages).*?\$([\d,]+\.?\d*)", re.IGNORECASE
)
_SS_TAX_RE = re.compile(
    r"(?:box\s*4\b|social\s+security\s+tax\s+withheld).*?\$([\d,]+\.?\d*)", re.IGNORECASE
)
_MEDICARE_WAGES_RE = re.compile(
    r"(?:box\s*5\b|medicare\s+wages).*?\$([\d,]+\.?\d*)", re.IGNORECASE
)
_MEDICARE_TAX_RE = re.compile(
    r"(?:box\s*6\b|medicare\s+tax\s+withheld).*?\$([\d,]+\.?\d*)", re.IGNORECASE
)
_STATE_WAGES_RE = re.compile(
    r"(?:box\s*16\b|state\s+wages).*?\$([\d,]+\.?\d*)", re.IGNORECASE
)
_STATE_TAX_RE = re.compile(
    r"(?:box\s*17\b|state\s+income\s+tax).*?\$([\d,]+\.?\d*)", re.IGNORECASE
)


def _money(m: Optional[re.Match]) -> Optional[float]:
    if m is None:
        return None
    return float(m.group(1).replace(",", "").replace("$", ""))


def parse_w2(text: str, source_filename: Optional[str] = None) -> ParsedSlip:
    fields: dict = {}
    text_fields: dict = {}

    year_m = _YEAR_RE.search(text)
    tax_year = int(year_m.group(1)) if year_m else None

    for key, pattern in [
        ("wages_tips_other", _WAGES_RE),
        ("federal_income_tax_withheld", _FED_TAX_RE),
        ("social_security_wages", _SS_WAGES_RE),
        ("social_security_tax_withheld", _SS_TAX_RE),
        ("medicare_wages", _MEDICARE_WAGES_RE),
        ("medicare_tax_withheld", _MEDICARE_TAX_RE),
        ("state_wages", _STATE_WAGES_RE),
        ("state_income_tax", _STATE_TAX_RE),
    ]:
        val = _money(pattern.search(text))
        if val is not None:
            fields[key] = val

    # Employer name (Box c)
    emp_m = re.search(r"employer(?:'s)?\s+name[\s:]+([^\n]{3,60})", text, re.IGNORECASE)
    if emp_m:
        text_fields["employer_name"] = emp_m.group(1).strip()

    # State abbreviation
    state_m = re.search(r"\b([A-Z]{2})\s+\d{6,}", text)
    if state_m:
        text_fields["state"] = state_m.group(1)

    confidence = "high" if "wages_tips_other" in fields else (
        "medium" if fields else "low"
    )
    return ParsedSlip(
        jurisdiction="US",
        form_type="W-2",
        tax_year=tax_year,
        fields=fields,
        text_fields=text_fields,
        source_filename=source_filename,
        extractor="rule",
        confidence=confidence,
        raw_text=text,
    )
