from __future__ import annotations

from typing import Optional

from wealthtax_agent.forms._helpers import detect_tax_year, find_box_amount
from wealthtax_agent.forms.base import FormExtractor
from wealthtax_agent.forms.registry import register
from wealthtax_agent.state import FormExtract


@register
class T3Extractor(FormExtractor):
    jurisdiction = "CA"
    form_code = "T3"
    classification_patterns = (
        "T3 Statement of Trust Income",
        "Statement of Trust Income",
    )

    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        fields = {}
        box_map = {
            "capital_gains": "21",
            "actual_eligible_dividends": "49",
            "taxable_eligible_dividends": "50",
            "other_income": "26",
            "foreign_non_business_income": "25",
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
