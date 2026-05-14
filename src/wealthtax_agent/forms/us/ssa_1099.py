from __future__ import annotations

from typing import Optional

from wealthtax_agent.forms._helpers import detect_tax_year, extract_amount_from_matching_line, find_box_amount
from wealthtax_agent.forms.base import FormExtractor
from wealthtax_agent.forms.registry import register
from wealthtax_agent.state import FormExtract


@register
class SSA1099Extractor(FormExtractor):
    jurisdiction = "US"
    form_code = "SSA-1099"
    classification_patterns = (
        "SSA-1099",
        "Social Security Benefit Statement",
    )

    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        fields = {}
        net_benefits = extract_amount_from_matching_line(text, r"net\s+benefits\s+for")
        if net_benefits is None:
            net_benefits = find_box_amount(text, "5")
        if net_benefits is not None:
            fields["net_benefits"] = net_benefits

        withheld = extract_amount_from_matching_line(text, r"federal\s+income\s+tax\s+withheld")
        if withheld is None:
            withheld = find_box_amount(text, "6")
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
