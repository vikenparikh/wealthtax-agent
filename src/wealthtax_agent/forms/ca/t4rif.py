from __future__ import annotations

from typing import Optional

from wealthtax_agent.forms._helpers import detect_tax_year, find_box_amount
from wealthtax_agent.forms.base import FormExtractor
from wealthtax_agent.forms.registry import register
from wealthtax_agent.state import FormExtract


@register
class T4RIFExtractor(FormExtractor):
    """Statement of Income from a Registered Retirement Income Fund."""

    jurisdiction = "CA"
    form_code = "T4RIF"
    classification_patterns = (
        "T4RIF",
        "Income from a Registered Retirement Income Fund",
        "Statement of Income from a RRIF",
    )

    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        fields = {}
        box_map = {
            "taxable_amount": "16",
            "other_income_or_deductions": "22",
            "tax_deducted": "28",
            "designated_benefit": "26",
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
