from __future__ import annotations

from typing import Optional

from wealthtax_agent.forms._helpers import detect_tax_year, extract_amount_from_matching_line, find_box_amount
from wealthtax_agent.forms.base import FormExtractor
from wealthtax_agent.forms.registry import register
from wealthtax_agent.state import FormExtract


@register
class T5Extractor(FormExtractor):
    jurisdiction = "CA"
    form_code = "T5"
    classification_patterns = (
        "T5 Statement of Investment Income",
        "Statement of Investment Income",
    )

    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        fields = {}
        # Box mapping (per CRA T5):
        #   Box 13 -> interest from Canadian sources
        #   Box 10/11 -> actual / taxable amount of non-eligible dividends
        #   Box 24/25 -> actual / taxable amount of eligible dividends
        box_map = {
            "interest_income": "13",
            "actual_non_eligible_dividends": "10",
            "taxable_non_eligible_dividends": "11",
            "actual_eligible_dividends": "24",
            "taxable_eligible_dividends": "25",
        }
        for field_name, box in box_map.items():
            value = find_box_amount(text, box)
            if value is not None:
                fields[field_name] = value

        if "interest_income" not in fields:
            value = extract_amount_from_matching_line(text, r"interest\s+from\s+canadian\s+sources")
            if value is not None:
                fields["interest_income"] = value
        if "taxable_eligible_dividends" not in fields:
            value = extract_amount_from_matching_line(text, r"eligible\s+dividends")
            if value is not None:
                fields["taxable_eligible_dividends"] = value
                fields.setdefault("dividends", value)
        if "dividends" not in fields and "taxable_eligible_dividends" in fields:
            fields["dividends"] = fields["taxable_eligible_dividends"]

        return FormExtract(
            form_code=self.form_code,
            jurisdiction=self.jurisdiction,
            tax_year=detect_tax_year(text),
            fields=fields,
            source_filename=source_filename,
            extractor="rule",
            confidence="high" if fields else "low",
        )
