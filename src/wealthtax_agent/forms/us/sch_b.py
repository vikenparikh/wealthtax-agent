from __future__ import annotations

from typing import Optional

from wealthtax_agent.forms._helpers import detect_tax_year, extract_amount_from_matching_line
from wealthtax_agent.forms.base import FormExtractor
from wealthtax_agent.forms.registry import register
from wealthtax_agent.state import FormExtract


@register
class ScheduleBExtractor(FormExtractor):
    jurisdiction = "US"
    form_code = "SCH-B"
    classification_patterns = (
        "Schedule B",
        "Interest and Ordinary Dividends",
    )

    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        fields = {}
        interest = extract_amount_from_matching_line(text, r"total\s+interest")
        if interest is not None:
            fields["total_interest"] = interest
        dividends = extract_amount_from_matching_line(text, r"total\s+ordinary\s+dividends")
        if dividends is not None:
            fields["total_ordinary_dividends"] = dividends
        return FormExtract(
            form_code=self.form_code,
            jurisdiction=self.jurisdiction,
            tax_year=detect_tax_year(text),
            fields=fields,
            source_filename=source_filename,
            extractor="rule",
            confidence="high" if fields else "low",
        )
