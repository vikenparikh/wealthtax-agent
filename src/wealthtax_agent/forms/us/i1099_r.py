from __future__ import annotations

from typing import Optional

from wealthtax_agent.forms._helpers import detect_tax_year, find_box_amount
from wealthtax_agent.forms.base import FormExtractor
from wealthtax_agent.forms.registry import register
from wealthtax_agent.state import FormExtract


@register
class Form1099RExtractor(FormExtractor):
    jurisdiction = "US"
    form_code = "1099-R"
    classification_patterns = (
        "1099-R",
        "Distributions From Pensions",
        "Retirement or Profit-Sharing Plans",
    )

    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        fields = {}
        box_map = {
            "gross_distribution": "1",
            "taxable_amount": "2a",
            "federal_income_tax_withheld": "4",
            "employee_contributions": "5",
            "distribution_code": "7",
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
