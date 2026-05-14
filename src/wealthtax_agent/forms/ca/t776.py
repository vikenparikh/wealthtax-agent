from __future__ import annotations

from typing import Optional

from wealthtax_agent.forms._helpers import detect_tax_year, extract_amount_from_matching_line
from wealthtax_agent.forms.base import FormExtractor
from wealthtax_agent.forms.registry import register
from wealthtax_agent.state import FormExtract


@register
class T776Extractor(FormExtractor):
    jurisdiction = "CA"
    form_code = "T776"
    classification_patterns = (
        "T776",
        "Statement of Real Estate Rentals",
    )

    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        fields = {}
        rental_revenue = extract_amount_from_matching_line(text, r"gross\s+rental\s+income|gross\s+rents")
        if rental_revenue is None:
            rental_revenue = extract_amount_from_matching_line(text, r"rental\s+revenue")
        if rental_revenue is not None:
            fields["gross_rental_income"] = rental_revenue

        expenses = extract_amount_from_matching_line(text, r"total\s+expenses")
        if expenses is not None:
            fields["total_expenses"] = expenses

        net_rental = extract_amount_from_matching_line(text, r"net\s+rental\s+income")
        if net_rental is not None:
            fields["net_rental_income"] = net_rental
        elif "gross_rental_income" in fields and "total_expenses" in fields:
            fields["net_rental_income"] = round(fields["gross_rental_income"] - fields["total_expenses"], 2)

        return FormExtract(
            form_code=self.form_code,
            jurisdiction=self.jurisdiction,
            tax_year=detect_tax_year(text),
            fields=fields,
            source_filename=source_filename,
            extractor="rule",
            confidence="high" if fields else "low",
        )
