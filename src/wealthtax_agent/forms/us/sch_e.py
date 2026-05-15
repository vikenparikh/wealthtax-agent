from __future__ import annotations

from typing import Optional

from wealthtax_agent.forms._helpers import detect_tax_year, extract_amount_from_matching_line
from wealthtax_agent.forms.base import FormExtractor
from wealthtax_agent.forms.registry import register
from wealthtax_agent.state import FormExtract


@register
class ScheduleEExtractor(FormExtractor):
    """Supplemental Income and Loss (rental + royalty + K-1 flow-through)."""

    jurisdiction = "US"
    form_code = "SCH-E"
    classification_patterns = (
        "Schedule E",
        "Supplemental Income and Loss",
    )

    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        fields = {}
        rents = extract_amount_from_matching_line(text, r"total\s+rents\s+received|rents\s+received")
        if rents is not None:
            fields["total_rents"] = rents
        royalties = extract_amount_from_matching_line(text, r"royalties\s+received|total\s+royalties")
        if royalties is not None:
            fields["total_royalties"] = royalties
        net = extract_amount_from_matching_line(text, r"net\s+(?:rental\s+real\s+estate\s+|)income")
        if net is not None:
            fields["net_supplemental_income"] = net
        return FormExtract(
            form_code=self.form_code,
            jurisdiction=self.jurisdiction,
            tax_year=detect_tax_year(text),
            fields=fields,
            source_filename=source_filename,
            extractor="rule",
            confidence="high" if fields else "low",
        )
