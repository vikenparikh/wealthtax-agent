from __future__ import annotations

from typing import Optional

from wealthtax_agent.forms._helpers import detect_tax_year, find_box_amount
from wealthtax_agent.forms.base import FormExtractor
from wealthtax_agent.forms.registry import register
from wealthtax_agent.state import FormExtract


@register
class T5013Extractor(FormExtractor):
    """Statement of Partnership Income."""

    jurisdiction = "CA"
    form_code = "T5013"
    classification_patterns = (
        "T5013",
        "Statement of Partnership Income",
    )

    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        fields = {}
        box_map = {
            "business_income_loss": "104",
            "professional_income_loss": "106",
            "rental_income": "107",
            "interest_income": "128",
            "actual_eligible_dividends": "132",
            "taxable_eligible_dividends": "133",
            "capital_gains": "151",
        }
        for field_name, box in box_map.items():
            value = find_box_amount(text, box)
            if value is not None:
                fields[field_name] = value
        return FormExtract(
            form_code=self.form_code,
            jurisdiction=self.jurisdiction,
            tax_year=detect_tax_year(text),
            fields=fields,
            source_filename=source_filename,
            extractor="rule",
            confidence="high" if fields else "low",
        )
