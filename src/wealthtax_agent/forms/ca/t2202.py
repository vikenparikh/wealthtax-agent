from __future__ import annotations

from typing import Optional

from wealthtax_agent.forms._helpers import detect_tax_year, extract_amount_from_matching_line
from wealthtax_agent.forms.base import FormExtractor
from wealthtax_agent.forms.registry import register
from wealthtax_agent.state import FormExtract


@register
class T2202Extractor(FormExtractor):
    jurisdiction = "CA"
    form_code = "T2202"
    classification_patterns = (
        "T2202",
        "Tuition and Enrolment Certificate",
        "Tuition Enrolment Certificate",
    )

    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        fields = {}
        eligible_fees = extract_amount_from_matching_line(text, r"eligible\s+tuition\s+fees")
        if eligible_fees is None:
            eligible_fees = extract_amount_from_matching_line(text, r"tuition\s+fees")
        if eligible_fees is not None:
            fields["eligible_tuition_fees"] = eligible_fees

        ft_months = extract_amount_from_matching_line(text, r"full[\s\-]?time\s+months")
        pt_months = extract_amount_from_matching_line(text, r"part[\s\-]?time\s+months")
        if ft_months is not None:
            fields["full_time_months"] = ft_months
        if pt_months is not None:
            fields["part_time_months"] = pt_months

        return FormExtract(
            form_code=self.form_code,
            jurisdiction=self.jurisdiction,
            tax_year=detect_tax_year(text),
            fields=fields,
            source_filename=source_filename,
            extractor="rule",
            confidence="high" if fields else "low",
        )
