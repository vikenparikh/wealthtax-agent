"""Build an IRS-MeF-shaped JSON draft. NOT certified for transmission."""

from __future__ import annotations

from typing import Any, Dict, List

from wealthtax_agent.state import DraftReturn, FormExtract


SCHEMA_VERSION = "0.1-draft"


def _safe_int(value, default: int = 0) -> int:
    """Tolerant int coercion mirroring us_engine._num_dependents: a non-numeric
    value (e.g. an NL correction stored uncoerced as "two") degrades to the
    default and is clamped non-negative, instead of raising ValueError and
    wiping the entire US artifact set in build_return_node's per-jurisdiction
    try/except."""
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


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
            "Dependents": _safe_int(user_answers.get("num_dependents", 0)),
            "StateOfResidence": user_answers.get("state_of_residence", ""),
        },
        "ReturnData": {
            "IRS1040": {
                # W-2 box 8 allocated tips are not in box 1 wages; the engine counts
                # them as a separate income component, so line 1a must add them back.
                "line1a_wages": round(line_items.get("wages", 0.0) + line_items.get("allocated_tips", 0.0), 2),
                "line2b_taxable_interest": line_items.get("interest_income", 0.0),
                "line3a_qualified_dividends": line_items.get("qualified_dividends", 0.0),
                "line3b_ordinary_dividends": line_items.get("ordinary_dividends", 0.0),
                "line4b_taxable_ira_distributions": 0.0,
                "line5b_taxable_pensions": line_items.get("taxable_pension", 0.0),
                "line6b_taxable_social_security": line_items.get("taxable_social_security", 0.0),
                "line7_capital_gain_loss": line_items.get("short_term_capital_gain", 0.0) + line_items.get("long_term_capital_gain", 0.0),
                # Form 1040 line 8 is the Schedule 1 catch-all. The engine folds many
                # income components into total_income (line 9) but the serializer
                # surfaced only other_misc_income here — so the breakdown silently
                # under-displayed self-employment (Sch C/1099-NEC/K-1/1099-K), rental
                # and royalty (1099-MISC), Schedule E supplemental, unemployment
                # (1099-G), taxable state refunds, taxable grants, and gambling
                # winnings. line 9 stays engine-truth, so this completes the display
                # without changing the bottom line. NOTE: 1099_k_payments is NOT added
                # separately — it is already inside self_employment_income (engine:
                # self_employment_income = nec + sch_c + k1 + k_payments).
                "line8_other_income": round(
                    line_items.get("other_misc_income", 0.0)
                    + line_items.get("self_employment_income", 0.0)
                    + line_items.get("rental_income", 0.0)
                    + line_items.get("royalty_income", 0.0)
                    + line_items.get("supplemental_income_sch_e", 0.0)
                    + line_items.get("unemployment_compensation", 0.0)
                    + line_items.get("state_tax_refund_taxable", 0.0)
                    + line_items.get("taxable_grants", 0.0)
                    + line_items.get("gambling_winnings", 0.0), 2),
                "line9_total_income": totals.get("total_income", 0.0),
                "line10_adjustments": line_items.get("student_loan_interest_deduction", 0.0),
                "line11_agi": line_items.get("agi", totals.get("agi", 0.0)),
                "line12_standard_deduction": credits.get("standard_deduction", 0.0),
                "line15_taxable_income": totals.get("taxable_income", 0.0),
                "line16_tax": line_items.get("ordinary_tax", 0.0) + line_items.get("preferential_tax", 0.0),
                # Form 1040 line 19 is "Child tax credit OR credit for other
                # dependents" (Schedule 8812) — the SUM of both. Surfacing only the
                # CTC understated line 19 for any filer with non-child dependents,
                # whose ODC the engine applies (federal_tax nets it) but the artifact
                # hid. Line 20 surfaces the Schedule-3 non-refundable credits
                # (education non-refundable + net PTC) the engine also nets into
                # federal_tax — previously invisible, so a hand-filer recomputing
                # line 22 from the shown credits would over-state their tax.
                "line19_ctc_or_odc": round(
                    credits.get("child_tax_credit", 0.0)
                    + line_items.get("credit_for_other_dependents", 0.0), 2),
                "line20_schedule3_nonrefundable_credits": round(
                    line_items.get("education_credit_nonrefundable", 0.0)
                    + line_items.get("premium_tax_credit", 0.0), 2),
                "line21_total_credits": round(
                    credits.get("child_tax_credit", 0.0)
                    + line_items.get("credit_for_other_dependents", 0.0)
                    + line_items.get("education_credit_nonrefundable", 0.0)
                    + line_items.get("premium_tax_credit", 0.0), 2),
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
