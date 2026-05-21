"""T4 parser — Statement of Remuneration Paid."""

from __future__ import annotations

import re
from typing import Optional

from wealthtax_agent.parsers.base import ParsedSlip

_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_EMPLOYMENT_RE = re.compile(
    r"(?:box\s*14|employment\s+income)[\s:]*\$?([\d,]+\.?\d*)", re.IGNORECASE
)
_CPP_RE = re.compile(
    r"(?:box\s*16|employee['s]*\s+cpp\s+contributions?)[\s:]*\$?([\d,]+\.?\d*)", re.IGNORECASE
)
_EI_RE = re.compile(
    r"(?:box\s*18|ei\s+(?:insurance\s+)?premiums?)[\s:]*\$?([\d,]+\.?\d*)", re.IGNORECASE
)
_FED_TAX_RE = re.compile(
    r"(?:box\s*22|income\s+tax\s+deducted)[\s:]*\$?([\d,]+\.?\d*)", re.IGNORECASE
)
_RPP_RE = re.compile(
    r"(?:box\s*52|pension\s+adjustment)[\s:]*\$?([\d,]+\.?\d*)", re.IGNORECASE
)
_UNION_RE = re.compile(
    r"(?:box\s*44|union\s+dues)[\s:]*\$?([\d,]+\.?\d*)", re.IGNORECASE
)


def _money(m: Optional[re.Match]) -> Optional[float]:
    if m is None:
        return None
    return float(m.group(1).replace(",", ""))


def parse_t4(text: str, source_filename: Optional[str] = None) -> ParsedSlip:
    fields: dict = {}
    text_fields: dict = {}

    year_m = _YEAR_RE.search(text)
    tax_year = int(year_m.group(1)) if year_m else None

    for key, pattern in [
        ("employment_income", _EMPLOYMENT_RE),
        ("employee_cpp_contributions", _CPP_RE),
        ("ei_premiums", _EI_RE),
        ("income_tax_deducted", _FED_TAX_RE),
        ("pension_adjustment", _RPP_RE),
        ("union_dues", _UNION_RE),
    ]:
        val = _money(pattern.search(text))
        if val is not None:
            fields[key] = val

    emp_m = re.search(r"employer['s]*\s+name[\s:]+([^\n]{3,60})", text, re.IGNORECASE)
    if emp_m:
        text_fields["employer_name"] = emp_m.group(1).strip()

    province_m = re.search(r"province\s+of\s+employment[\s:]+([A-Z]{2})", text, re.IGNORECASE)
    if province_m:
        text_fields["province"] = province_m.group(1)

    confidence = "high" if "employment_income" in fields else (
        "medium" if fields else "low"
    )
    return ParsedSlip(
        jurisdiction="CA",
        form_type="T4",
        tax_year=tax_year,
        fields=fields,
        text_fields=text_fields,
        source_filename=source_filename,
        extractor="rule",
        confidence=confidence,
        raw_text=text,
    )
