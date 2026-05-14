from __future__ import annotations

from typing import Optional

from wealthtax_agent.forms._helpers import detect_tax_year, extract_amount_from_matching_line
from wealthtax_agent.forms.base import FormExtractor
from wealthtax_agent.forms.registry import register
from wealthtax_agent.state import FormExtract


@register
class ScheduleAExtractor(FormExtractor):
    jurisdiction = "US"
    form_code = "SCH-A"
    classification_patterns = (
        "Schedule A",
        "Itemized Deductions",
    )

    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        fields = {}
        medical = extract_amount_from_matching_line(text, r"medical\s+(?:and\s+dental\s+)?expenses")
        if medical is not None:
            fields["medical_expenses"] = medical
        salt = extract_amount_from_matching_line(text, r"state\s+and\s+local\s+(?:income|sales)\s+taxes")
        if salt is not None:
            fields["state_local_taxes"] = salt
        mortgage = extract_amount_from_matching_line(text, r"home\s+mortgage\s+interest")
        if mortgage is not None:
            fields["mortgage_interest"] = mortgage
        charity = extract_amount_from_matching_line(text, r"gifts\s+to\s+charity")
        if charity is not None:
            fields["charitable_gifts"] = charity
        return FormExtract(
            form_code=self.form_code,
            jurisdiction=self.jurisdiction,
            tax_year=detect_tax_year(text),
            fields=fields,
            source_filename=source_filename,
            extractor="rule",
            confidence="high" if fields else "low",
        )
