from __future__ import annotations

from typing import Optional

from wealthtax_agent.forms._helpers import detect_tax_year, extract_amount_from_matching_line
from wealthtax_agent.forms.base import FormExtractor
from wealthtax_agent.forms.registry import register
from wealthtax_agent.state import FormExtract


@register
class RRSPExtractor(FormExtractor):
    jurisdiction = "CA"
    form_code = "RRSP"
    classification_patterns = (
        "RRSP Contribution Receipt",
        "Official RRSP Contribution Receipt",
        "RRSP Receipt",
    )

    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        fields = {}
        contribs = extract_amount_from_matching_line(text, r"total\s+rrsp\s+contributions")
        if contribs is None:
            contribs = extract_amount_from_matching_line(text, r"rrsp\s+contributions")
        if contribs is not None:
            fields["rrsp_contributions"] = contribs

        first_60 = extract_amount_from_matching_line(text, r"first\s+60\s+days")
        if first_60 is not None:
            fields["first_60_days_contribution"] = first_60

        return FormExtract(
            form_code=self.form_code,
            jurisdiction=self.jurisdiction,
            tax_year=detect_tax_year(text),
            fields=fields,
            source_filename=source_filename,
            extractor="rule",
            confidence="high" if fields else "low",
        )
