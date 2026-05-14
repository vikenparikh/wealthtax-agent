from __future__ import annotations

from typing import Optional

from wealthtax_agent.forms._helpers import detect_tax_year, extract_amount_from_matching_line, find_box_amount
from wealthtax_agent.forms.base import FormExtractor
from wealthtax_agent.forms.registry import register
from wealthtax_agent.state import FormExtract


@register
class Form1099IntExtractor(FormExtractor):
    jurisdiction = "US"
    form_code = "1099-INT"
    classification_patterns = (
        "1099-INT",
        "Interest Income",
    )

    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        fields = {}
        boxes = {
            "interest_income": "1",
            "early_withdrawal_penalty": "2",
            "us_treasury_interest": "3",
            "federal_income_tax_withheld": "4",
            "tax_exempt_interest": "8",
        }
        for field_name, box in boxes.items():
            value = find_box_amount(text, box)
            if value is not None:
                fields[field_name] = value
        if "interest_income" not in fields:
            value = extract_amount_from_matching_line(text, r"interest\s+income")
            if value is not None:
                fields["interest_income"] = value
        return FormExtract(
            form_code=self.form_code,
            jurisdiction=self.jurisdiction,
            tax_year=detect_tax_year(text),
            fields=fields,
            source_filename=source_filename,
            extractor="rule",
            confidence="high" if fields else "low",
        )
