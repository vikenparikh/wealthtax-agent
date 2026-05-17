from __future__ import annotations

from typing import Optional

from wealthtax_agent.forms._helpers import detect_tax_year, extract_amount_from_matching_line
from wealthtax_agent.forms.base import FormExtractor
from wealthtax_agent.forms.registry import register
from wealthtax_agent.state import FormExtract


@register
class Form8889Extractor(FormExtractor):
    """Health Savings Accounts (HSAs)."""

    jurisdiction = "US"
    form_code = "8889"
    classification_patterns = (
        "Form 8889",
        "Health Savings Accounts",
    )

    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        fields = {}
        contrib = extract_amount_from_matching_line(text, r"hsa\s+contributions?\s*:")
        if contrib is None:
            contrib = extract_amount_from_matching_line(text, r"line\s+2\s*:")
        if contrib is not None:
            fields["hsa_contributions"] = contrib
        deduction = extract_amount_from_matching_line(text, r"hsa\s+deduction\s*:")
        if deduction is not None:
            fields["hsa_deduction"] = deduction
        distributions = extract_amount_from_matching_line(text, r"distributions\s*:")
        if distributions is not None:
            fields["hsa_distributions"] = distributions
        return FormExtract(
            form_code=self.form_code,
            jurisdiction=self.jurisdiction,
            tax_year=detect_tax_year(text),
            fields=fields,
            source_filename=source_filename,
            extractor="rule",
            confidence="high" if fields else "low",
        )
