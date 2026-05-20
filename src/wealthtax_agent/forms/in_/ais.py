"""AIS — Annual Information Statement (interest/dividends/property sales)."""

from __future__ import annotations

from typing import Optional

from wealthtax_agent.forms._helpers import detect_tax_year, extract_amount_from_matching_line
from wealthtax_agent.forms.base import FormExtractor
from wealthtax_agent.forms.registry import register
from wealthtax_agent.state import FormExtract


@register
class AISExtractor(FormExtractor):
    jurisdiction = "IN"
    form_code = "AIS"
    classification_patterns = (
        "Annual Information Statement",
        "AIS for FY",
        "Taxpayer Information Summary",
        "TIS",
    )

    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        fields = {}
        mappings = {
            "interest_income": r"interest\s+(?:from|on)\s+(?:savings|deposits|bonds|fixed\s+deposits)|interest\s+income",
            "dividend_income": r"dividend\s+(?:income|received)",
            "sale_of_securities": r"sale\s+of\s+(?:securities|units|mutual\s+funds)",
            "sale_of_property": r"sale\s+of\s+(?:immovable\s+property|land)",
            "purchase_of_property": r"purchase\s+of\s+(?:immovable\s+property|land)",
            "credit_card_payments": r"credit\s+card\s+payments",
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
