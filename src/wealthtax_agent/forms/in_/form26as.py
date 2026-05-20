"""Form 26AS — annual tax-credit statement (TDS aggregator)."""

from __future__ import annotations

from typing import Optional

from wealthtax_agent.forms._helpers import detect_tax_year, extract_amount_from_matching_line
from wealthtax_agent.forms.base import FormExtractor
from wealthtax_agent.forms.registry import register
from wealthtax_agent.state import FormExtract


@register
class Form26ASExtractor(FormExtractor):
    jurisdiction = "IN"
    form_code = "FORM-26AS"
    classification_patterns = (
        "Form 26AS",
        "Annual Tax Statement",
        "Annual Information Statement",
        "26AS",
    )

    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        fields = {}
        mappings = {
            "total_tds": r"total\s+tds|tds\s+total|total\s+amount\s+of\s+tax\s+deducted",
            "advance_tax_paid": r"advance\s+tax|self[\s\-]?assessment\s+tax",
            "refund_received": r"refund\s+received|refund\s+issued",
        }
        for field_name, pattern in mappings.items():
            value = extract_amount_from_matching_line(text, pattern)
            if value is not None:
                fields[field_name] = value

        return FormExtract(
            form_code=self.form_code,
            jurisdiction=self.jurisdiction,
            tax_year=detect_tax_year(text),
            fields=fields,
            source_filename=source_filename,
            extractor="rule",
            confidence="medium" if fields else "low",
        )
