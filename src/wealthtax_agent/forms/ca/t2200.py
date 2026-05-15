from __future__ import annotations

from typing import Optional

from wealthtax_agent.forms._helpers import detect_tax_year, extract_amount_from_matching_line
from wealthtax_agent.forms.base import FormExtractor
from wealthtax_agent.forms.registry import register
from wealthtax_agent.state import FormExtract


@register
class T2200Extractor(FormExtractor):
    """Declaration of Conditions of Employment.

    T2200 itself does not carry a dollar amount; it certifies the employee is
    required to incur expenses. We extract whatever total the employee has
    typed onto the form as ``employment_expenses`` (claimed on line 22900).
    """

    jurisdiction = "CA"
    form_code = "T2200"
    classification_patterns = (
        "T2200",
        "Declaration of Conditions of Employment",
    )

    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        fields = {}
        expenses = extract_amount_from_matching_line(
            text, r"(?:total\s+)?employment\s+expenses"
        )
        if expenses is None:
            expenses = extract_amount_from_matching_line(text, r"motor\s+vehicle\s+expenses")
        if expenses is not None:
            fields["employment_expenses"] = expenses
        return FormExtract(
            form_code=self.form_code,
            jurisdiction=self.jurisdiction,
            tax_year=detect_tax_year(text),
            fields=fields,
            source_filename=source_filename,
            extractor="rule",
            confidence="high" if fields else "low",
        )
