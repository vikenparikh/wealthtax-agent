from __future__ import annotations

from typing import Optional

from wealthtax_agent.forms._helpers import detect_tax_year, extract_amount_from_matching_line
from wealthtax_agent.forms.base import FormExtractor
from wealthtax_agent.forms.registry import register
from wealthtax_agent.state import FormExtract


@register
class Form1095AExtractor(FormExtractor):
    """Health Insurance Marketplace Statement (drives Premium Tax Credit)."""

    jurisdiction = "US"
    form_code = "1095-A"
    classification_patterns = (
        "1095-A",
        "Health Insurance Marketplace Statement",
    )

    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        fields = {}
        premium = extract_amount_from_matching_line(text, r"annual\s+enrollment\s+premiums?\s*:")
        if premium is not None:
            fields["annual_premiums"] = premium
        slcsp = extract_amount_from_matching_line(text, r"annual\s+(?:second\s+lowest\s+cost\s+silver\s+plan|slcsp)\s*:")
        if slcsp is not None:
            fields["annual_slcsp"] = slcsp
        aptc = extract_amount_from_matching_line(text, r"annual\s+advance\s+payment\s+of\s+ptc\s*:")
        if aptc is None:
            aptc = extract_amount_from_matching_line(text, r"advance\s+payment\s+of\s+premium\s+tax\s+credit\s*:")
        if aptc is not None:
            fields["advance_ptc"] = aptc
        return FormExtract(
            form_code=self.form_code,
            jurisdiction=self.jurisdiction,
            tax_year=detect_tax_year(text),
            fields=fields,
            source_filename=source_filename,
            extractor="rule",
            confidence="high" if fields else "low",
        )
