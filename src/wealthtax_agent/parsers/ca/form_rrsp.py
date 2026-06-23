"""RRSP parser — T4RSP Statement of RRSP Income and receipt stubs."""

from __future__ import annotations

import re
from typing import Optional

from wealthtax_agent.parsers.base import ParsedSlip

_YEAR_RE = re.compile(r"\b(20\d{2})\b")
# T4RSP boxes. Box 22 is the authoritative income line, so it is searched FIRST:
# an explicit "Box 22: $5,000" always wins over the weaker prose signal. The
# prose fallback is split out because the form *title* — "Statement of RRSP
# Income" — also contains "RRSP income"; in flattened PDF text the year often
# trails the title on the same line, and the old combined regex captured that
# trailing year (e.g. 2024) as the income amount.
_WITHDRAWALS_BOX_RE = re.compile(r"box\s*22[\s:]*\$?([\d,]+\.?\d*)", re.IGNORECASE)
_WITHDRAWALS_LABEL_RE = re.compile(
    r"rrsp\s+(?:income|withdrawals?|payments?)[\s:]*\$?([\d,]+\.?\d*)", re.IGNORECASE
)
_TAX_DEDUCTED_RE = re.compile(
    r"(?:box\s*30|income\s+tax\s+deducted)[\s:]*\$?([\d,]+\.?\d*)", re.IGNORECASE
)
# RRSP contribution receipt
_CONTRIBUTION_RE = re.compile(
    r"(?:rrsp\s+)?contribution[\s:]*\$?([\d,]+\.?\d*)", re.IGNORECASE
)
_PLAN_RE = re.compile(r"plan\s+(?:number|no[\.]?)[\s:]+(\w{6,20})", re.IGNORECASE)


def _money(m: Optional[re.Match]) -> Optional[float]:
    if m is None:
        return None
    return float(m.group(1).replace(",", ""))


def parse_rrsp(text: str, source_filename: Optional[str] = None) -> ParsedSlip:
    fields: dict = {}
    text_fields: dict = {}

    year_m = _YEAR_RE.search(text)
    tax_year = int(year_m.group(1)) if year_m else None

    # Box 22 first; only fall back to the prose label when no box line exists.
    withdrawal = _money(_WITHDRAWALS_BOX_RE.search(text))
    if withdrawal is None:
        label_val = _money(_WITHDRAWALS_LABEL_RE.search(text))
        # Guard against the title-collision: the form header "Statement of RRSP
        # Income <year>" must never be read as the income amount.
        if label_val is not None and not (
            tax_year is not None and label_val == float(tax_year)
        ):
            withdrawal = label_val
    tax = _money(_TAX_DEDUCTED_RE.search(text))
    contribution = _money(_CONTRIBUTION_RE.search(text))

    if withdrawal is not None:
        fields["rrsp_income"] = withdrawal
    if tax is not None:
        fields["income_tax_deducted"] = tax
    if contribution is not None:
        fields["rrsp_contribution"] = contribution

    plan_m = _PLAN_RE.search(text)
    if plan_m:
        text_fields["plan_number"] = plan_m.group(1)

    # Determine if this is a T4RSP or a contribution receipt
    form_type = "T4RSP" if withdrawal is not None else "RRSP-RECEIPT"

    confidence = "high" if fields else "low"
    return ParsedSlip(
        jurisdiction="CA",
        form_type=form_type,
        tax_year=tax_year,
        fields=fields,
        text_fields=text_fields,
        source_filename=source_filename,
        extractor="rule",
        confidence=confidence,
        raw_text=text,
    )
