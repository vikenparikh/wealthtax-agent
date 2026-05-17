from __future__ import annotations

from typing import Optional

from wealthtax_agent.forms._helpers import detect_tax_year, find_box_amount
from wealthtax_agent.forms.base import FormExtractor
from wealthtax_agent.forms.registry import register
from wealthtax_agent.state import FormExtract


@register
class Form5498Extractor(FormExtractor):
    """IRA Contribution Information."""

    jurisdiction = "US"
    form_code = "5498"
    classification_patterns = (
        "Form 5498",
        "IRA Contribution Information",
    )

    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        fields = {}
        box_map = {
            "ira_contributions": "1",
            "rollover_contributions": "2",
            "roth_conversion_amount": "3",
            "recharacterized_contributions": "4",
            "fair_market_value": "5",
            "roth_ira_contributions": "10",
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
