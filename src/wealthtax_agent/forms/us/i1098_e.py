from __future__ import annotations

from typing import Optional

from wealthtax_agent.forms._helpers import detect_tax_year, extract_amount_from_matching_line, find_box_amount
from wealthtax_agent.forms.base import FormExtractor
from wealthtax_agent.forms.registry import register
from wealthtax_agent.state import FormExtract


@register
class Form1098EExtractor(FormExtractor):
    jurisdiction = "US"
    form_code = "1098-E"
    classification_patterns = (
        "1098-E",
        "Student Loan Interest Statement",
    )

    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        fields = {}
        interest = find_box_amount(text, "1")
        if interest is None:
            interest = extract_amount_from_matching_line(text, r"student\s+loan\s+interest")
        if interest is not None:
            fields["student_loan_interest"] = interest
        return FormExtract(
            form_code=self.form_code,
            jurisdiction=self.jurisdiction,
            tax_year=detect_tax_year(text),
            fields=fields,
            source_filename=source_filename,
            extractor="rule",
            confidence="high" if fields else "low",
        )
