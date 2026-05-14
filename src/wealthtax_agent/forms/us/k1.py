from __future__ import annotations

from typing import Optional

from wealthtax_agent.forms._helpers import detect_tax_year, find_box_amount
from wealthtax_agent.forms.base import FormExtractor
from wealthtax_agent.forms.registry import register
from wealthtax_agent.state import FormExtract


@register
class K1Extractor(FormExtractor):
    jurisdiction = "US"
    form_code = "K-1"
    classification_patterns = (
        "Schedule K-1",
        "Partner's Share of Income",
        "Shareholder's Share of Income",
        "Beneficiary's Share",
    )

    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        fields = {}
        # K-1 box structure varies by entity. Capture a handful of common
        # income boxes and surface them; engine treats unknowns as ordinary.
        box_map = {
            "ordinary_business_income": "1",
            "net_rental_real_estate_income": "2",
            "interest_income": "5",
            "ordinary_dividends": "6a",
            "qualified_dividends": "6b",
            "net_short_term_capital_gain": "8",
            "net_long_term_capital_gain": "9a",
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
