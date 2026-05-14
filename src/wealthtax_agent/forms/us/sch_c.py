from __future__ import annotations

from typing import Optional

from wealthtax_agent.forms._helpers import detect_tax_year, extract_amount_from_matching_line
from wealthtax_agent.forms.base import FormExtractor
from wealthtax_agent.forms.registry import register
from wealthtax_agent.state import FormExtract


@register
class ScheduleCExtractor(FormExtractor):
    jurisdiction = "US"
    form_code = "SCH-C"
    classification_patterns = (
        "Schedule C",
        "Profit or Loss From Business",
    )

    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        fields = {}
        gross = extract_amount_from_matching_line(text, r"gross\s+receipts(?:\s+or\s+sales)?")
        if gross is not None:
            fields["gross_receipts"] = gross
        expenses = extract_amount_from_matching_line(text, r"total\s+expenses")
        if expenses is not None:
            fields["total_expenses"] = expenses
        net = extract_amount_from_matching_line(text, r"net\s+profit\s+or\s+\(loss\)|net\s+profit|net\s+loss")
        if net is not None:
            fields["net_profit"] = net
        elif "gross_receipts" in fields and "total_expenses" in fields:
            fields["net_profit"] = round(fields["gross_receipts"] - fields["total_expenses"], 2)
        return FormExtract(
            form_code=self.form_code,
            jurisdiction=self.jurisdiction,
            tax_year=detect_tax_year(text),
            fields=fields,
            source_filename=source_filename,
            extractor="rule",
            confidence="high" if fields else "low",
        )
