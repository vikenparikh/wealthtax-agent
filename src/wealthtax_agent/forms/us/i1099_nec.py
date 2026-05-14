from __future__ import annotations

from typing import Optional

from wealthtax_agent.forms._helpers import detect_tax_year, extract_amount_from_matching_line, find_box_amount
from wealthtax_agent.forms.base import FormExtractor
from wealthtax_agent.forms.registry import register
from wealthtax_agent.state import FormExtract


@register
class Form1099NecExtractor(FormExtractor):
    jurisdiction = "US"
    form_code = "1099-NEC"
    classification_patterns = (
        "1099-NEC",
        "Nonemployee Compensation",
    )

    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        fields = {}
        nec = find_box_amount(text, "1")
        if nec is None:
            nec = extract_amount_from_matching_line(text, r"nonemployee\s+compensation")
        if nec is not None:
            fields["nonemployee_compensation"] = nec

        withheld = find_box_amount(text, "4")
        if withheld is not None:
            fields["federal_income_tax_withheld"] = withheld

        return FormExtract(
            form_code=self.form_code,
            jurisdiction=self.jurisdiction,
            tax_year=detect_tax_year(text),
            fields=fields,
            source_filename=source_filename,
            extractor="rule",
            confidence="high" if fields else "low",
        )
