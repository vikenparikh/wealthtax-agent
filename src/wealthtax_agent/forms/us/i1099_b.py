from __future__ import annotations

import re
from typing import Optional

from wealthtax_agent.forms._helpers import detect_tax_year, find_box_amount
from wealthtax_agent.forms.base import FormExtractor
from wealthtax_agent.forms.registry import register
from wealthtax_agent.state import FormExtract


@register
class Form1099BExtractor(FormExtractor):
    jurisdiction = "US"
    form_code = "1099-B"
    classification_patterns = (
        "1099-B",
        "Proceeds from Broker",
    )

    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        fields = {}
        # Box 1d Proceeds, 1e Cost basis, Box 2 = Short-term or Long-term marker
        proceeds = find_box_amount(text, "1d")
        cost = find_box_amount(text, "1e")
        if proceeds is not None:
            fields["proceeds"] = proceeds
        if cost is not None:
            fields["cost_basis"] = cost
        if proceeds is not None and cost is not None:
            fields["gain_loss"] = round(proceeds - cost, 2)

        text_lower = text.lower()
        if re.search(r"long[\s\-]?term", text_lower):
            fields["term"] = 1.0  # 1 = long-term
        elif re.search(r"short[\s\-]?term", text_lower):
            fields["term"] = 0.0  # 0 = short-term

        return FormExtract(
            form_code=self.form_code,
            jurisdiction=self.jurisdiction,
            tax_year=detect_tax_year(text),
            fields=fields,
            source_filename=source_filename,
            extractor="rule",
            confidence="high" if fields else "low",
        )
