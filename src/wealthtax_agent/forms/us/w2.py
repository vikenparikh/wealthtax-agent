from __future__ import annotations

from typing import Optional

from wealthtax_agent.forms._helpers import detect_tax_year, extract_amount_from_matching_line, find_box_amount
from wealthtax_agent.forms.base import FormExtractor
from wealthtax_agent.forms.registry import register
from wealthtax_agent.state import FormExtract


@register
class W2Extractor(FormExtractor):
    jurisdiction = "US"
    form_code = "W-2"
    classification_patterns = (
        "Form W-2",
        "Wage and Tax Statement",
        "W-2 Wage",
    )

    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        fields = {}
        boxes = {
            "wages": "1",
            "federal_income_tax_withheld": "2",
            "social_security_wages": "3",
            "social_security_tax_withheld": "4",
            "medicare_wages": "5",
            "medicare_tax_withheld": "6",
            "social_security_tips": "7",
            "allocated_tips": "8",
            "dependent_care_benefits": "10",
            "nonqualified_plans": "11",
            "state_wages": "16",
            "state_income_tax": "17",
        }
        for field_name, box in boxes.items():
            value = find_box_amount(text, box)
            if value is not None:
                fields[field_name] = value

        if "wages" not in fields:
            value = extract_amount_from_matching_line(text, r"wages,\s*tips,?\s*other\s+compensation")
            if value is not None:
                fields["wages"] = value

        return FormExtract(
            form_code=self.form_code,
            jurisdiction=self.jurisdiction,
            tax_year=detect_tax_year(text),
            fields=fields,
            source_filename=source_filename,
            extractor="rule",
            confidence="high" if fields else "low",
        )
