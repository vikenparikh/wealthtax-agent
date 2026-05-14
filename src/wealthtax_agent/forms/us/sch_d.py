from __future__ import annotations

from typing import Optional

from wealthtax_agent.forms._helpers import detect_tax_year, extract_amount_from_matching_line
from wealthtax_agent.forms.base import FormExtractor
from wealthtax_agent.forms.registry import register
from wealthtax_agent.state import FormExtract


@register
class ScheduleDExtractor(FormExtractor):
    jurisdiction = "US"
    form_code = "SCH-D"
    classification_patterns = (
        "Schedule D",
        "Capital Gains and Losses",
    )

    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        fields = {}
        st_gain = extract_amount_from_matching_line(text, r"net\s+short[\s\-]?term\s+capital\s+gain")
        lt_gain = extract_amount_from_matching_line(text, r"net\s+long[\s\-]?term\s+capital\s+gain")
        if st_gain is not None:
            fields["net_short_term_capital_gain"] = st_gain
        if lt_gain is not None:
            fields["net_long_term_capital_gain"] = lt_gain
        return FormExtract(
            form_code=self.form_code,
            jurisdiction=self.jurisdiction,
            tax_year=detect_tax_year(text),
            fields=fields,
            source_filename=source_filename,
            extractor="rule",
            confidence="high" if fields else "low",
        )
