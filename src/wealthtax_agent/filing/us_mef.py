"""Build an IRS-MeF-shaped JSON draft. NOT certified for transmission."""

from __future__ import annotations

from typing import Any, Dict, List

from wealthtax_agent.state import DraftReturn, FormExtract


SCHEMA_VERSION = "0.1-draft"


def serialize_1040(draft: DraftReturn, extracts: List[FormExtract], year: int, user_answers: Dict[str, str] | None = None) -> Dict[str, Any]:
    user_answers = user_answers or {}
    line_items = draft.line_items or {}
    totals = draft.totals or {}
    credits = draft.credits or {}

    return {
        "transmissible": False,
        "schema_version": SCHEMA_VERSION,
        "note": "Prototype draft only. NOT IRS MeF certified. Do not transmit.",
        "ReturnHeader": {
            "TaxYear": year,
            "FilingStatus": user_answers.get("filing_status", "single"),
            "Dependents": int(user_answers.get("num_dependents", 0) or 0),
            "StateOfResidence": user_answers.get("state_of_residence", ""),
        },
        "ReturnData": {
            "IRS1040": {
                "line1a_wages": line_items.get("wages", 0.0),
                "line2b_taxable_interest": line_items.get("interest_income", 0.0),
                "line3a_qualified_dividends": line_items.get("qualified_dividends", 0.0),
                "line3b_ordinary_dividends": line_items.get("ordinary_dividends", 0.0),
                "line4b_taxable_ira_distributions": 0.0,
                "line5b_taxable_pensions": line_items.get("taxable_pension", 0.0),
                "line6b_taxable_social_security": line_items.get("taxable_social_security", 0.0),
                "line7_capital_gain_loss": line_items.get("short_term_capital_gain", 0.0) + line_items.get("long_term_capital_gain", 0.0),
                "line8_other_income": line_items.get("other_misc_income", 0.0),
                "line9_total_income": totals.get("total_income", 0.0),
                "line10_adjustments": line_items.get("student_loan_interest_deduction", 0.0),
                "line11_agi": line_items.get("agi", totals.get("agi", 0.0)),
                "line12_standard_deduction": credits.get("standard_deduction", 0.0),
                "line15_taxable_income": totals.get("taxable_income", 0.0),
                "line16_tax": line_items.get("ordinary_tax", 0.0) + line_items.get("preferential_tax", 0.0),
                "line19_child_tax_credit": credits.get("child_tax_credit", 0.0),
                "line22_total_tax_before_other": line_items.get("federal_tax", 0.0),
                "line23_other_taxes_self_employment": line_items.get("self_employment_tax", 0.0),
                "line24_total_tax": totals.get("total_tax", 0.0),
                "line25a_federal_income_tax_withheld": line_items.get("tax_withheld", 0.0),
                "line33_total_payments": line_items.get("tax_withheld", 0.0),
                "line34_overpayment": totals.get("refund", 0.0),
                "line37_amount_you_owe": totals.get("balance_owing", 0.0),
            },
            "Slips": [
                {
                    "form_code": e.form_code,
                    "source": e.source_filename,
                    "fields": e.fields,
                }
                for e in extracts
                if e.jurisdiction == "US"
            ],
        },
    }
