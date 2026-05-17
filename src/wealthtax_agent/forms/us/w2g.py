from __future__ import annotations

from typing import Optional

from wealthtax_agent.forms._helpers import detect_tax_year, find_box_amount
from wealthtax_agent.forms.base import FormExtractor
from wealthtax_agent.forms.registry import register
from wealthtax_agent.state import FormExtract


@register
class W2GExtractor(FormExtractor):
    """Certain Gambling Winnings."""

    jurisdiction = "US"
    form_code = "W-2G"
    classification_patterns = (
        "W-2G",
        "Certain Gambling Winnings",
    )

    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        fields = {}
        winnings = find_box_amount(text, "1")
        if winnings is not None:
            fields["gambling_winnings"] = winnings
        withheld = find_box_amount(text, "4")
        if withheld is not None:
            fields["federal_income_tax_withheld"] = withheld
        return FormExtract(
            form_code=self.form_code,
            jurisdiction=self.jurisdiction,
            tax_year=detect_tax_year(text),
            fields=fields,
            source_filename=source_filename,
            extractor="rule",
            confidence="high" if fields else "low",
        )
