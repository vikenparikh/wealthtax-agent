from __future__ import annotations

from typing import Optional

from wealthtax_agent.forms._helpers import detect_tax_year, extract_amount_from_matching_line
from wealthtax_agent.forms.base import FormExtractor
from wealthtax_agent.forms.registry import register
from wealthtax_agent.state import FormExtract


@register
class Form8949Extractor(FormExtractor):
    """Sales and Other Dispositions of Capital Assets."""

    jurisdiction = "US"
    form_code = "8949"
    classification_patterns = (
        "Form 8949",
        "Sales and Other Dispositions of Capital Assets",
    )

    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        fields = {}
        proceeds = extract_amount_from_matching_line(text, r"total\s+proceeds\s*:")
        cost = extract_amount_from_matching_line(text, r"total\s+cost\s+basis\s*:")
        gain = extract_amount_from_matching_line(text, r"total\s+gain(?:/loss)?\s*:")
        if proceeds is not None:
            fields["proceeds"] = proceeds
        if cost is not None:
            fields["cost_basis"] = cost
        if gain is not None:
            fields["gain_loss"] = gain
        elif proceeds is not None and cost is not None:
            fields["gain_loss"] = round(proceeds - cost, 2)
        return FormExtract(
            form_code=self.form_code,
            jurisdiction=self.jurisdiction,
            tax_year=detect_tax_year(text),
            fields=fields,
            source_filename=source_filename,
            extractor="rule",
            confidence="high" if fields else "low",
        )
