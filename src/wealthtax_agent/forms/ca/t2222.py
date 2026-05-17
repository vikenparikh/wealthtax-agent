from __future__ import annotations

from typing import Optional

from wealthtax_agent.forms._helpers import detect_tax_year, extract_amount_from_matching_line
from wealthtax_agent.forms.base import FormExtractor
from wealthtax_agent.forms.registry import register
from wealthtax_agent.state import FormExtract


@register
class T2222Extractor(FormExtractor):
    """Northern Residents Deductions (Zone A / Zone B)."""

    jurisdiction = "CA"
    form_code = "T2222"
    classification_patterns = (
        "T2222",
        "Northern Residents Deductions",
    )

    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        fields = {}
        residency = extract_amount_from_matching_line(text, r"residency\s+deduction\s*:")
        if residency is not None:
            fields["residency_deduction"] = residency
        travel = extract_amount_from_matching_line(text, r"travel\s+deduction\s*:")
        if travel is not None:
            fields["travel_deduction"] = travel
        return FormExtract(
            form_code=self.form_code,
            jurisdiction=self.jurisdiction,
            tax_year=detect_tax_year(text),
            fields=fields,
            source_filename=source_filename,
            extractor="rule",
            confidence="high" if fields else "low",
        )
