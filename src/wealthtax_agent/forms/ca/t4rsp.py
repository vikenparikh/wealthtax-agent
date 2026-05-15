from __future__ import annotations

from typing import Optional

from wealthtax_agent.forms._helpers import detect_tax_year, find_box_amount
from wealthtax_agent.forms.base import FormExtractor
from wealthtax_agent.forms.registry import register
from wealthtax_agent.state import FormExtract


@register
class T4RSPExtractor(FormExtractor):
    """Statement of RRSP Income (withdrawals from an RRSP)."""

    jurisdiction = "CA"
    form_code = "T4RSP"
    classification_patterns = (
        "T4RSP",
        "Statement of RRSP Income",
    )

    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        fields = {}
        box_map = {
            "annuity_payments": "16",
            "refund_of_premiums": "18",
            "withdrawal_and_commutation": "22",
            "other_income": "28",
            "tax_deducted": "30",
            "hbp_withdrawal": "27",
            "llp_withdrawal": "25",
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
