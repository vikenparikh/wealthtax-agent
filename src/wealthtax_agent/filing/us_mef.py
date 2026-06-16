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

    # Federal-only line 24 (total tax) and line 33 (total payments), computed once
    # so the refund/owe lines reconcile (line34 = max(0, 33-24), line37 = max(0,
    # 24-33)) instead of pulling the engine's COMBINED federal+state totals. The
    # net Premium Tax Credit is intentionally NOT in line 33 — the engine already
    # nets it into federal_tax (line 24), so adding it here would double-count it.
    line24_total_tax = round(line_items.get("federal_tax", 0.0) + line_items.get("self_employment_tax", 0.0), 2)
    # Total payments must include EVERY refundable item the engine credits in its
    # balance (us_engine: balance = total_tax - withholding - excess_ss - addl_medicare
    # - actc - eitc - education_refundable). Omitting the additional-Medicare
    # over-withholding (Form 8959 Part IV, Sch 3 line 11) or the refundable AOTC
    # (Form 8863, 1040 line 29) understates line34_overpayment / overstates
    # line37_amount_you_owe, contradicting the engine's own refund/balance_owing.
    # Net PTC stays EXCLUDED (already netted into federal_tax / line 24).
    line33_total_payments = round(
        line_items.get("tax_withheld", 0.0)
        + line_items.get("additional_child_tax_credit", 0.0)
        + line_items.get("earned_income_credit", 0.0)
        + line_items.get("excess_social_security_tax", 0.0)
        + line_items.get("additional_medicare_tax_withheld", 0.0)
        + line_items.get("education_credit_refundable", 0.0),
        2,
    )

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
                # Federal-form total tax = line 22 + line 23 (federal only; state
                # income tax belongs on a state artifact, not the federal 1040).
                "line24_total_tax": line24_total_tax,
                "line25a_federal_income_tax_withheld": line_items.get("tax_withheld", 0.0),
                "line25c_additional_medicare_tax_withheld": line_items.get("additional_medicare_tax_withheld", 0.0),
                "line27_earned_income_credit": line_items.get("earned_income_credit", 0.0),
                "line28_additional_child_tax_credit": line_items.get("additional_child_tax_credit", 0.0),
                "line29_refundable_education_credit": line_items.get("education_credit_refundable", 0.0),
                # Total payments = withholding + ACTC (line 28) + EITC (line 27) +
                # excess SS + additional-Medicare over-withholding (line 25c) +
                # refundable AOTC (line 29). Net PTC is excluded (already netted into
                # line 24).
                "line33_total_payments": line33_total_payments,
                "line34_overpayment": round(max(0.0, line33_total_payments - line24_total_tax), 2),
                "line37_amount_you_owe": round(max(0.0, line24_total_tax - line33_total_payments), 2),
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
