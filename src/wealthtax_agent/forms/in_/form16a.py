"""Form 16A — TDS certificate for non-salary payments (rent, FD interest, etc.)."""

from __future__ import annotations

from typing import Optional

from wealthtax_agent.forms._helpers import detect_tax_year, extract_amount_from_matching_line
from wealthtax_agent.forms.base import FormExtractor
from wealthtax_agent.forms.registry import register
from wealthtax_agent.state import FormExtract


@register
class Form16AExtractor(FormExtractor):
    jurisdiction = "IN"
    form_code = "FORM-16A"
    classification_patterns = (
        "Form 16A",
        "FORM NO. 16A",
        "TDS on income other than salary",
        "Certificate u/s 203",
    )

    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        fields = {}
        mappings = {
            "interest_income": r"interest\s+(?:income|paid|on\s+fd|on\s+fixed)",
            "dividend_income": r"dividend",
            "rent_paid": r"rent\s+paid",
            "professional_fees": r"professional\s+fees|fees\s+for\s+technical",
            "tds_deducted": r"tax\s+deducted|tds\s+deducted",
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
