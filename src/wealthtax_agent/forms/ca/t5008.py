from __future__ import annotations

from typing import Optional

from wealthtax_agent.forms._helpers import detect_tax_year, find_box_amount
from wealthtax_agent.forms.base import FormExtractor
from wealthtax_agent.forms.registry import register
from wealthtax_agent.state import FormExtract


@register
class T5008Extractor(FormExtractor):
    jurisdiction = "CA"
    form_code = "T5008"
    classification_patterns = (
        "T5008",
        "Statement of Securities Transactions",
    )

    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        fields = {}
        # Box 20 = cost or book value, Box 21 = proceeds of disposition
        proceeds = find_box_amount(text, "21")
        cost = find_box_amount(text, "20")
        if proceeds is not None:
            fields["proceeds"] = proceeds
        if cost is not None:
            fields["cost_basis"] = cost
        if proceeds is not None and cost is not None:
            fields["capital_gain"] = round(proceeds - cost, 2)
        return FormExtract(
            form_code=self.form_code,
            jurisdiction=self.jurisdiction,
            tax_year=detect_tax_year(text),
            fields=fields,
            source_filename=source_filename,
            extractor="rule",
            confidence="high" if fields else "low",
        )
