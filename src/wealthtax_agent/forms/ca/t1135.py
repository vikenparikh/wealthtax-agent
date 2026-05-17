from __future__ import annotations

from typing import Optional

from wealthtax_agent.forms._helpers import detect_tax_year, extract_amount_from_matching_line
from wealthtax_agent.forms.base import FormExtractor
from wealthtax_agent.forms.registry import register
from wealthtax_agent.state import FormExtract


@register
class T1135Extractor(FormExtractor):
    """Foreign Income Verification Statement.

    Required for Canadian residents whose specified foreign property cost
    exceeded $100,000 CAD at any time during the year. Filed separately from
    the T1.
    """

    jurisdiction = "CA"
    form_code = "T1135"
    classification_patterns = (
        "T1135",
        "Foreign Income Verification Statement",
    )

    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        fields = {}
        total_cost = extract_amount_from_matching_line(text, r"total\s+cost\s+amount\s*:")
        if total_cost is None:
            total_cost = extract_amount_from_matching_line(text, r"highest\s+cost\s+amount\s*:")
        if total_cost is not None:
            fields["total_foreign_property_cost"] = total_cost
        income = extract_amount_from_matching_line(text, r"income\s+from\s+foreign\s+property\s*:")
        if income is not None:
            fields["foreign_property_income"] = income
        return FormExtract(
            form_code=self.form_code,
            jurisdiction=self.jurisdiction,
            tax_year=detect_tax_year(text),
            fields=fields,
            source_filename=source_filename,
            extractor="rule",
            confidence="high" if fields else "low",
        )
