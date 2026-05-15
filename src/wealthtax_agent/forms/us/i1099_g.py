from __future__ import annotations

from typing import Optional

from wealthtax_agent.forms._helpers import detect_tax_year, find_box_amount
from wealthtax_agent.forms.base import FormExtractor
from wealthtax_agent.forms.registry import register
from wealthtax_agent.state import FormExtract


@register
class Form1099GExtractor(FormExtractor):
    """Certain Government Payments (unemployment, state tax refunds, etc.)."""

    jurisdiction = "US"
    form_code = "1099-G"
    classification_patterns = (
        "1099-G",
        "Certain Government Payments",
    )

    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        fields = {}
        box_map = {
            "unemployment_compensation": "1",
            "state_local_tax_refund": "2",
            "federal_income_tax_withheld": "4",
            "agricultural_payments": "7",
            "taxable_grants": "6",
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
