from __future__ import annotations

from typing import Optional

from wealthtax_agent.forms._helpers import detect_tax_year, extract_amount_from_matching_line
from wealthtax_agent.forms.base import FormExtractor
from wealthtax_agent.forms.registry import register
from wealthtax_agent.state import FormExtract


@register
class Form2555Extractor(FormExtractor):
    """Foreign Earned Income Exclusion (FEIE)."""

    jurisdiction = "US"
    form_code = "2555"
    classification_patterns = (
        "Form 2555",
        "Foreign Earned Income Exclusion",
        "Foreign Earned Income",
    )

    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        fields = {}
        feie = extract_amount_from_matching_line(text, r"foreign\s+earned\s+income\s*:")
        if feie is None:
            feie = extract_amount_from_matching_line(text, r"total\s+foreign\s+earned\s+income\s*:")
        if feie is not None:
            fields["foreign_earned_income"] = feie
        excluded = extract_amount_from_matching_line(text, r"amount\s+excluded\s*:")
        if excluded is not None:
            fields["foreign_earned_income_excluded"] = excluded
        return FormExtract(
            form_code=self.form_code,
            jurisdiction=self.jurisdiction,
            tax_year=detect_tax_year(text),
            fields=fields,
            source_filename=source_filename,
            extractor="rule",
            confidence="high" if fields else "low",
        )
