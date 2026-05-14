from __future__ import annotations

from typing import Optional

from wealthtax_agent.forms._helpers import detect_tax_year, extract_amount_from_matching_line, find_box_amount
from wealthtax_agent.forms.base import FormExtractor
from wealthtax_agent.forms.registry import register
from wealthtax_agent.state import FormExtract


@register
class Form1099DivExtractor(FormExtractor):
    jurisdiction = "US"
    form_code = "1099-DIV"
    classification_patterns = (
        "1099-DIV",
        "Dividends and Distributions",
    )

    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        fields = {}
        # Box 1a Total ordinary dividends; 1b Qualified dividends; 2a Total capital gain distribution
        boxes = {
            "ordinary_dividends": "1a",
            "qualified_dividends": "1b",
            "capital_gain_distributions": "2a",
            "unrecaptured_section_1250_gain": "2b",
            "section_1202_gain": "2c",
            "collectibles_28_pct": "2d",
            "nondividend_distributions": "3",
            "federal_income_tax_withheld": "4",
            "section_199A_dividends": "5",
        }
        for field_name, box in boxes.items():
            value = find_box_amount(text, box)
            if value is not None:
                fields[field_name] = value
        if "ordinary_dividends" not in fields:
            value = extract_amount_from_matching_line(text, r"total\s+ordinary\s+dividends")
            if value is not None:
                fields["ordinary_dividends"] = value
        if "qualified_dividends" not in fields:
            value = extract_amount_from_matching_line(text, r"qualified\s+dividends")
            if value is not None:
                fields["qualified_dividends"] = value
        return FormExtract(
            form_code=self.form_code,
            jurisdiction=self.jurisdiction,
            tax_year=detect_tax_year(text),
            fields=fields,
            source_filename=source_filename,
            extractor="rule",
            confidence="high" if fields else "low",
        )
