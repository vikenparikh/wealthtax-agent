"""Capital-gain statement (broker-provided summary, e.g. Zerodha/Groww).

The engine looks for pre/post Jul 23 2024 split fields. This extractor
recognises the common Indian broker labels and maps them into the schema
``in_engine._capital_gains_split`` consumes.
"""

from __future__ import annotations

from typing import Optional

from wealthtax_agent.forms._helpers import detect_tax_year, extract_amount_from_matching_line
from wealthtax_agent.forms.base import FormExtractor
from wealthtax_agent.forms.registry import register
from wealthtax_agent.state import FormExtract


@register
class StockGainExtractor(FormExtractor):
    jurisdiction = "IN"
    form_code = "STOCK-GAIN"
    classification_patterns = (
        "Capital Gains Statement",
        "STCG",
        "LTCG",
        "Short Term Capital Gain",
        "Long Term Capital Gain",
        "Tax P&L",
    )

    def extract(self, text: str, source_filename: Optional[str] = None) -> FormExtract:
        fields = {}
        mappings = {
            "stcg_equity_pre_change": r"stcg\s+equity\s+pre|short[\s\-]?term\s+(?:capital\s+)?gain\s+equity\s+pre",
            "stcg_equity_post_change": r"stcg\s+equity\s+post|short[\s\-]?term\s+(?:capital\s+)?gain\s+equity\s+post",
            "stcg_equity": r"^\s*stcg(?:\s+equity)?\b|short[\s\-]?term\s+capital\s+gain\b(?!\s+other)",
            "ltcg_equity_pre_change": r"ltcg\s+equity\s+pre|long[\s\-]?term\s+(?:capital\s+)?gain\s+equity\s+pre",
            "ltcg_equity_post_change": r"ltcg\s+equity\s+post|long[\s\-]?term\s+(?:capital\s+)?gain\s+equity\s+post",
            "ltcg_equity": r"^\s*ltcg(?:\s+equity)?\b|long[\s\-]?term\s+capital\s+gain\b(?!\s+other)",
            "stcg_other": r"stcg\s+other|short[\s\-]?term\s+(?:capital\s+)?gain\s+other",
            "ltcg_other": r"ltcg\s+other|long[\s\-]?term\s+(?:capital\s+)?gain\s+other",
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
            confidence="medium" if fields else "low",
        )
