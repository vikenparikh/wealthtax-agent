from __future__ import annotations

from typing import Optional

from wealthtax_agent.forms._helpers import detect_tax_year, extract_amount_from_matching_line
from wealthtax_agent.forms.base import FormExtractor
from wealthtax_agent.forms.registry import register
from wealthtax_agent.state import FormExtract


@register
class ScheduleSEExtractor(FormExtractor):
    """Self-Employment Tax."""

    jurisdiction = "US"
    form_code = "SCH-SE"
    classification_patterns = (
        "Schedule SE",
        "Self-Employment Tax",
    )

    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        fields = {}
        net = extract_amount_from_matching_line(text, r"net\s+earnings\s+from\s+self[\s\-]?employment\s*:")
        if net is None:
            net = extract_amount_from_matching_line(text, r"net\s+profit\s+from\s+self[\s\-]?employment\s*:")
        if net is not None:
            fields["net_se_earnings"] = net
        # Require a colon so the form title "Schedule SE (Form 1040)
        # Self-Employment Tax" doesn't satisfy the match.
        tax = extract_amount_from_matching_line(text, r"self[\s\-]?employment\s+tax\s*:")
        if tax is not None:
            fields["self_employment_tax"] = tax
        return FormExtract(
            form_code=self.form_code,
            jurisdiction=self.jurisdiction,
            tax_year=detect_tax_year(text),
            fields=fields,
            source_filename=source_filename,
            extractor="rule",
            confidence="high" if fields else "low",
        )
