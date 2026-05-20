"""Form 16 — TDS certificate issued by Indian employers."""

from __future__ import annotations

from typing import Optional

from wealthtax_agent.forms._helpers import detect_tax_year, extract_amount_from_matching_line
from wealthtax_agent.forms.base import FormExtractor
from wealthtax_agent.forms.registry import register
from wealthtax_agent.state import FormExtract


@register
class Form16Extractor(FormExtractor):
    jurisdiction = "IN"
    form_code = "FORM-16"
    classification_patterns = (
        "Form 16",
        "FORM NO. 16",
        "Certificate under section 203",
        "Salary paid",
        "TDS Certificate",
    )

    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        fields = {}
        mappings = {
            "gross_salary": r"gross\s+salary",
            "basic_salary": r"basic\s+salary",
            "hra_received": r"house\s+rent\s+allowance|hra\s+received",
            "standard_deduction_salary": r"standard\s+deduction",
            "section_80c_declared": r"deduction\s+under\s+section\s+80c|section\s+80c",
            "section_80d_declared": r"section\s+80d",
            "section_80e_declared": r"section\s+80e",
            "tds_deducted": r"tax\s+deducted\s+at\s+source|total\s+tds|tds\s+deducted",
            "professional_tax": r"professional\s+tax",
        }
        for field_name, pattern in mappings.items():
            value = extract_amount_from_matching_line(text, pattern)
            if value is not None:
                fields[field_name] = value

        return FormExtract(
            form_code=self.form_code,
            jurisdiction=self.jurisdiction,
            tax_year=detect_tax_year(text),
            fields=fields,
            source_filename=source_filename,
            extractor="rule",
            confidence="high" if fields else "low",
        )
