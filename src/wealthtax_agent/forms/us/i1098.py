from __future__ import annotations

from typing import Optional

from wealthtax_agent.forms._helpers import detect_tax_year, find_box_amount
from wealthtax_agent.forms.base import FormExtractor
from wealthtax_agent.forms.registry import register
from wealthtax_agent.state import FormExtract


@register
class Form1098Extractor(FormExtractor):
    jurisdiction = "US"
    form_code = "1098"
    classification_patterns = (
        "Form 1098",
        "Mortgage Interest Statement",
    )

    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        fields = {}
        box_map = {
            "mortgage_interest_received": "1",
            "outstanding_mortgage_principal": "2",
            "mortgage_origination_date": None,
            "points_paid": "6",
        }
        for field_name, box in box_map.items():
            if box is None:
                continue
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
