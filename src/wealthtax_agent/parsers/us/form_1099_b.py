"""1099-B parser — broker/barter exchange transactions.

Extracts proceeds (Box 1d), cost basis (Box 1e), short/long-term indicator
(Box 2), wash-sale disallowed amount (Box 1g), and description.
Falls back to ClaudeCLILLM on low-confidence rule extraction.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from wealthtax_agent.parsers.base import ParsedSlip

log = logging.getLogger(__name__)

_BOX_RE = re.compile(
    r"(?:box\s*|box\s+)?1[de][\s:)\-]*([\d,]+\.?\d*)", re.IGNORECASE
)
_PROCEEDS_RE = re.compile(r"proceeds[\s:]*\$?([\d,]+\.?\d*)", re.IGNORECASE)
_BASIS_RE = re.compile(r"cost(?:\s+basis)?[\s:]*\$?([\d,]+\.?\d*)", re.IGNORECASE)
_WASH_RE = re.compile(
    r"wash[\s\-]sale\s+(?:loss\s+)?disallowed[\s:]*\$?([\d,]+\.?\d*)", re.IGNORECASE
)
_YEAR_RE = re.compile(r"\b(20\d{2})\b")


def _money(m: Optional[re.Match]) -> Optional[float]:
    if m is None:
        return None
    return float(m.group(1).replace(",", ""))


def parse_1099b(
    text: str,
    source_filename: Optional[str] = None,
    use_llm_fallback: bool = True,
) -> ParsedSlip:
    """Parse plain text extracted from a 1099-B into a ``ParsedSlip``."""
    fields: dict = {}
    text_fields: dict = {}

    year_m = _YEAR_RE.search(text)
    tax_year = int(year_m.group(1)) if year_m else None

    proceeds = _money(_PROCEEDS_RE.search(text))
    cost = _money(_BASIS_RE.search(text))
    wash = _money(_WASH_RE.search(text))

    if proceeds is not None:
        fields["proceeds"] = proceeds
    if cost is not None:
        fields["cost_basis"] = cost
    if wash is not None:
        fields["wash_sale_loss_disallowed"] = wash
    if proceeds is not None and cost is not None:
        fields["gain_loss"] = round(proceeds - cost, 2)

    text_lower = text.lower()
    if re.search(r"long[\s\-]?term", text_lower):
        fields["term"] = 1.0
        text_fields["term_label"] = "long-term"
    elif re.search(r"short[\s\-]?term", text_lower):
        fields["term"] = 0.0
        text_fields["term_label"] = "short-term"

    # Try to grab description / security name
    desc_m = re.search(r"description[\s:]+([^\n]{3,60})", text, re.IGNORECASE)
    if desc_m:
        text_fields["description"] = desc_m.group(1).strip()

    confidence = "high" if (proceeds is not None and cost is not None) else (
        "medium" if fields else "low"
    )

    if confidence == "low" and use_llm_fallback:
        slip = _llm_fallback(text, source_filename, tax_year)
        if slip is not None:
            return slip

    return ParsedSlip(
        jurisdiction="US",
        form_type="1099-B",
        tax_year=tax_year,
        fields=fields,
        text_fields=text_fields,
        source_filename=source_filename,
        extractor="rule",
        confidence=confidence,
        raw_text=text,
    )


def _llm_fallback(
    text: str, source_filename: Optional[str], tax_year: Optional[int]
) -> Optional[ParsedSlip]:
    try:
        from wealthtax_agent.services.claude_llm import get_tax_llm

        llm = get_tax_llm()
        prompt = (
            "Extract all numeric fields from this IRS Form 1099-B text. "
            "Return JSON: {proceeds, cost_basis, gain_loss, wash_sale_loss_disallowed, "
            "term (0=short,1=long), tax_year (int), description (str)}. "
            "Use null for missing values.\n\n"
            + text[:3000]
        )
        schema = (
            '{"proceeds": 0.0, "cost_basis": 0.0, "gain_loss": 0.0, '
            '"wash_sale_loss_disallowed": 0.0, "term": null, "tax_year": null, '
            '"description": ""}'
        )
        result = llm.complete_json(prompt, schema)
        fields = {
            k: float(v)
            for k, v in result.items()
            if k not in ("tax_year", "description") and v is not None
        }
        return ParsedSlip(
            jurisdiction="US",
            form_type="1099-B",
            tax_year=result.get("tax_year") or tax_year,
            fields=fields,
            text_fields={"description": str(result.get("description", ""))},
            source_filename=source_filename,
            extractor="llm",
            confidence="medium",
            raw_text=text,
        )
    except Exception as exc:
        log.warning("1099-B LLM fallback failed: %s", exc)
        return None
