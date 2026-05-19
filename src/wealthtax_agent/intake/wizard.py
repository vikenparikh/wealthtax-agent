"""Build ``FormExtract`` objects from manually-typed values.

Each supported intake form lists the fields the engine actually consumes
(see ``engines/ca_engine.py`` and ``engines/us_engine.py``). The wizard
validates types and snaps the result into the same shape OCR-driven
extracts produce, so downstream code can't tell the difference.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict

from wealthtax_agent.state import FormExtract


class FieldSpec(TypedDict, total=False):
    name: str
    label: str
    kind: str  # "number" | "text" | "choice"
    options: List[str]
    required: bool


def _f(name: str, label: str, *, kind: str = "number", required: bool = False, options: Optional[List[str]] = None) -> FieldSpec:
    spec: FieldSpec = {"name": name, "label": label, "kind": kind, "required": required}
    if options:
        spec["options"] = options
    return spec


# Field specs per supported intake form. Engines already know how to consume
# every field listed here, so a fully populated manual entry is equivalent to
# the rule-based extractor running against an uploaded slip.
SUPPORTED_INTAKE_FORMS: Dict[str, Dict[str, Any]] = {
    # Canada
    "T4": {
        "jurisdiction": "CA",
        "fields": [
            _f("employment_income", "Box 14 — Employment income", required=True),
            _f("income_tax_deducted", "Box 22 — Income tax deducted"),
            _f("cpp_contributions", "Box 16 — CPP contributions"),
            _f("ei_premiums", "Box 18 — EI premiums"),
            _f("rpp_contributions", "Box 20 — RPP contributions"),
            _f("union_dues", "Box 44 — Union dues"),
        ],
    },
    "T5": {
        "jurisdiction": "CA",
        "fields": [
            _f("interest_income", "Box 13 — Interest from Canadian sources"),
            _f("taxable_eligible_dividends", "Box 25 — Taxable amount of eligible dividends"),
            _f("actual_non_eligible_dividends", "Box 10 — Actual non-eligible dividends"),
        ],
    },
    "RRSP": {
        "jurisdiction": "CA",
        "fields": [
            _f("rrsp_contributions", "Total RRSP contributions", required=True),
            _f("first_60_days_contribution", "First-60-days contribution"),
        ],
    },
    "T2202": {
        "jurisdiction": "CA",
        "fields": [
            _f("eligible_tuition_fees", "Eligible tuition fees", required=True),
            _f("full_time_months", "Full-time months"),
            _f("part_time_months", "Part-time months"),
        ],
    },
    "T776": {
        "jurisdiction": "CA",
        "fields": [
            _f("gross_rental_income", "Gross rental income"),
            _f("total_expenses", "Total expenses"),
            _f("net_rental_income", "Net rental income", required=True),
        ],
    },
    "T2125": {
        "jurisdiction": "CA",
        "fields": [
            _f("gross_business_income", "Gross business income"),
            _f("total_expenses", "Total expenses"),
            _f("net_business_income", "Net business income", required=True),
        ],
    },

    # United States
    "W-2": {
        "jurisdiction": "US",
        "fields": [
            _f("wages", "Box 1 — Wages, tips, other compensation", required=True),
            _f("federal_income_tax_withheld", "Box 2 — Federal income tax withheld"),
            _f("social_security_wages", "Box 3 — Social security wages"),
            _f("medicare_wages", "Box 5 — Medicare wages"),
            _f("state_wages", "Box 16 — State wages"),
            _f("state_income_tax", "Box 17 — State income tax"),
        ],
    },
    "1099-INT": {
        "jurisdiction": "US",
        "fields": [
            _f("interest_income", "Box 1 — Interest income", required=True),
            _f("us_treasury_interest", "Box 3 — US Treasury interest"),
            _f("federal_income_tax_withheld", "Box 4 — Federal income tax withheld"),
        ],
    },
    "1099-DIV": {
        "jurisdiction": "US",
        "fields": [
            _f("ordinary_dividends", "Box 1a — Total ordinary dividends", required=True),
            _f("qualified_dividends", "Box 1b — Qualified dividends"),
            _f("capital_gain_distributions", "Box 2a — Capital gain distributions"),
        ],
    },
    "1099-NEC": {
        "jurisdiction": "US",
        "fields": [
            _f("nonemployee_compensation", "Box 1 — Nonemployee compensation", required=True),
            _f("federal_income_tax_withheld", "Box 4 — Federal income tax withheld"),
        ],
    },
    "1099-R": {
        "jurisdiction": "US",
        "fields": [
            _f("gross_distribution", "Box 1 — Gross distribution", required=True),
            _f("taxable_amount", "Box 2a — Taxable amount"),
            _f("federal_income_tax_withheld", "Box 4 — Federal income tax withheld"),
        ],
    },
    "SCH-C": {
        "jurisdiction": "US",
        "fields": [
            _f("gross_receipts", "Gross receipts"),
            _f("total_expenses", "Total expenses"),
            _f("net_profit", "Net profit", required=True),
        ],
    },
}


def field_spec_for(form_code: str) -> List[FieldSpec]:
    return list(SUPPORTED_INTAKE_FORMS.get(form_code.upper(), {}).get("fields", []))


def manual_extract(form_code: str, values: Dict[str, Any], *, source_filename: Optional[str] = None) -> FormExtract:
    """Build a ``FormExtract`` from a dict of user-supplied values.

    Unknown form codes raise ``ValueError`` so callers fail fast.
    """
    spec = SUPPORTED_INTAKE_FORMS.get(form_code.upper())
    if spec is None:
        raise ValueError(f"Form {form_code} is not in the manual intake set; upload it instead.")

    field_names = {f["name"] for f in spec["fields"]}
    cleaned: Dict[str, float] = {}
    for name, value in values.items():
        if name not in field_names or value in (None, ""):
            continue
        try:
            cleaned[name] = float(str(value).replace(",", "").replace("$", "").strip())
        except (TypeError, ValueError):
            continue

    return FormExtract(
        form_code=form_code.upper(),
        jurisdiction=spec["jurisdiction"],
        fields=cleaned,
        source_filename=source_filename or f"manual-{form_code.lower()}",
        extractor="rule",
        confidence="high" if cleaned else "low",
    )
