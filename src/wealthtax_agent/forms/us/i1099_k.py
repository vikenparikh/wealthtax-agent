from __future__ import annotations

from typing import Optional

from wealthtax_agent.forms._helpers import detect_tax_year, extract_amount_from_matching_line, find_box_amount
from wealthtax_agent.forms.base import FormExtractor
from wealthtax_agent.forms.registry import register
from wealthtax_agent.state import FormExtract


@register
class Form1099KExtractor(FormExtractor):
    """Payment Card and Third Party Network Transactions."""

    jurisdiction = "US"
    form_code = "1099-K"
    classification_patterns = (
        "1099-K",
        "Payment Card and Third Party Network Transactions",
    )

    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        fields = {}
        gross = find_box_amount(text, "1a")
        if gross is None:
            gross = extract_amount_from_matching_line(text, r"gross\s+amount")
        if gross is not None:
            fields["gross_payments"] = gross

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
