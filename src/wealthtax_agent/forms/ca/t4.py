from __future__ import annotations

from typing import Optional

from wealthtax_agent.forms._helpers import detect_tax_year, extract_amount_from_matching_line, find_box_amount
from wealthtax_agent.forms.base import FormExtractor
from wealthtax_agent.forms.registry import register
from wealthtax_agent.state import FormExtract


@register
class T4Extractor(FormExtractor):
    jurisdiction = "CA"
    form_code = "T4"
    classification_patterns = (
        "T4 Statement of Remuneration",
        "Statement of Remuneration Paid",
        "T4 slip",
    )

    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        fields = {}
        boxes = {
            "employment_income": ["14"],
            "income_tax_deducted": ["22"],
            "cpp_contributions": ["16"],
            "ei_premiums": ["18"],
            "pension_adjustment": ["52"],
            "rpp_contributions": ["20"],
            "union_dues": ["44"],
            "charitable_donations": ["46"],
        }
        for field_name, candidates in boxes.items():
            for box in candidates:
                value = find_box_amount(text, box)
                if value is not None:
                    fields[field_name] = value
                    break

        if "employment_income" not in fields:
            value = extract_amount_from_matching_line(text, r"employment\s*income")
            if value is not None:
                fields["employment_income"] = value

        return FormExtract(
            form_code=self.form_code,
            jurisdiction=self.jurisdiction,
            tax_year=detect_tax_year(text),
            fields=fields,
            source_filename=source_filename,
            extractor="rule",
            confidence="high" if fields else "low",
        )
