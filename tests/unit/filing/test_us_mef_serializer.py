"""Dedicated tests for the US MeF JSON serializer (filing/us_mef.py).

serialize_1040 was only spot-checked in test_filing_artifacts.py
(transmissible + tax-year). These tests pin the ReturnHeader handling
(filing-status / dependents coercion / state), the 1040 line mapping —
including the two composed lines (capital gain = STCG + LTCG, tax =
ordinary + preferential) and the AGI line_items/totals fallback — the
US-only Slips filter, defaults, and JSON-serializability with the
transmissible=False security flag intact.
"""

import json

from wealthtax_agent.filing.us_mef import SCHEMA_VERSION, serialize_1040
from wealthtax_agent.state import DraftReturn, FormExtract


def _draft(line_items=None, totals=None, credits=None):
    return DraftReturn(
        jurisdiction="US",
        line_items=line_items or {},
        totals=totals or {},
        credits=credits or {},
    )


def test_envelope_flags_and_schema():
    payload = serialize_1040(_draft(), [], 2025)
    assert payload["transmissible"] is False
    assert payload["schema_version"] == SCHEMA_VERSION
    assert "Do not transmit" in payload["note"]


def test_return_header_defaults_when_no_user_answers():
    header = serialize_1040(_draft(), [], 2025)["ReturnHeader"]
    assert header["TaxYear"] == 2025
    assert header["FilingStatus"] == "single"
    assert header["Dependents"] == 0
    assert header["StateOfResidence"] == ""


def test_return_header_reads_user_answers_and_coerces_dependents():
    header = serialize_1040(
        _draft(), [], 2025,
        {"filing_status": "married_joint", "num_dependents": "3", "state_of_residence": "CA"},
    )["ReturnHeader"]
    assert header["FilingStatus"] == "married_joint"
    assert header["Dependents"] == 3          # coerced from str
    assert header["StateOfResidence"] == "CA"


def test_dependents_blank_string_coerces_to_zero():
    header = serialize_1040(_draft(), [], 2025, {"num_dependents": ""})["ReturnHeader"]
    assert header["Dependents"] == 0


def test_capital_gain_line_sums_short_and_long_term():
    draft = _draft(line_items={"short_term_capital_gain": 1500.0, "long_term_capital_gain": 4000.0})
    f1040 = serialize_1040(draft, [], 2025)["ReturnData"]["IRS1040"]
    assert f1040["line7_capital_gain_loss"] == 5500.0


def test_tax_line_sums_ordinary_and_preferential():
    draft = _draft(line_items={"ordinary_tax": 9000.0, "preferential_tax": 750.0})
    f1040 = serialize_1040(draft, [], 2025)["ReturnData"]["IRS1040"]
    assert f1040["line16_tax"] == 9750.0


def test_agi_prefers_line_items_then_totals():
    from_line_items = serialize_1040(_draft(line_items={"agi": 71000.0}), [], 2025)
    assert from_line_items["ReturnData"]["IRS1040"]["line11_agi"] == 71000.0
    from_totals = serialize_1040(_draft(totals={"agi": 68000.0}), [], 2025)
    assert from_totals["ReturnData"]["IRS1040"]["line11_agi"] == 68000.0


def test_core_lines_map_from_line_items_and_totals():
    draft = _draft(
        line_items={
            "wages": 84000.0,
            "interest_income": 320.0,
            "qualified_dividends": 600.0,
            "ordinary_dividends": 800.0,
            "student_loan_interest_deduction": 2500.0,
            "standard_deduction": 0.0,
            "tax_withheld": 12000.0,
            "federal_tax": 11000.0,
            "self_employment_tax": 0.0,
        },
        totals={"total_income": 85720.0, "taxable_income": 70000.0, "total_tax": 11000.0,
                "refund": 1000.0, "balance_owing": 0.0},
        credits={"standard_deduction": 14600.0, "child_tax_credit": 2000.0},
    )
    f = serialize_1040(draft, [], 2025)["ReturnData"]["IRS1040"]
    assert f["line1a_wages"] == 84000.0
    assert f["line2b_taxable_interest"] == 320.0
    assert f["line9_total_income"] == 85720.0
    assert f["line10_adjustments"] == 2500.0
    assert f["line12_standard_deduction"] == 14600.0   # from credits
    assert f["line15_taxable_income"] == 70000.0
    assert f["line19_ctc_or_odc"] == 2000.0  # CTC 2000 + ODC 0
    assert f["line24_total_tax"] == 11000.0   # federal_tax + se_tax (no state here)
    assert f["line25a_federal_income_tax_withheld"] == 12000.0
    assert f["line34_overpayment"] == 1000.0


def test_line24_excludes_state_income_tax():
    """Form 1040 line 24 (Total tax) is federal-only = line 22 (federal tax, incl.
    AMT/NIIT) + line 23 (SE tax). The engine's totals['total_tax'] also bundles
    STATE income tax, which has no place on the federal 1040 — a CA/NY filer's
    federal Total Tax was overstated by the full state tax.

    Here federal_tax $8,000 + SE $1,000 = $9,000, with $3,000 of state tax making
    totals['total_tax'] = $12,000.

    FAILS before the fix: line24 = $12,000 (includes state tax)."""
    draft = _draft(
        line_items={"federal_tax": 8000.0, "self_employment_tax": 1000.0},
        totals={"total_tax": 12000.0},   # 8000 fed + 1000 SE + 3000 state
    )
    f = serialize_1040(draft, [], 2025)["ReturnData"]["IRS1040"]
    assert f["line24_total_tax"] == 9000.0


def test_line24_reconciles_with_line22_plus_line23():
    """Invariant: line 24 must equal line 22 + line 23 (the federal-form definition)."""
    draft = _draft(line_items={"federal_tax": 8000.0, "self_employment_tax": 1000.0},
                   totals={"total_tax": 12000.0})
    f = serialize_1040(draft, [], 2025)["ReturnData"]["IRS1040"]
    assert f["line24_total_tax"] == f["line22_total_tax_before_other"] + f["line23_other_taxes_self_employment"]


def test_line33_includes_actc_and_excess_ss_and_line28_present():
    """Form 1040 line 33 (total payments) = withholding + ACTC (line 28) + excess
    Social Security tax (Sch 3 line 11). The serializer previously mapped line 33
    to withholding only and had no line 28 at all, so a low-income family's
    refundable ACTC and a multi-employer filer's excess SS never appeared as
    payments.

    Low-income filer: $0 tax, $300 withheld, $1,700 ACTC, $500 excess SS.

    FAILS before: no line28 key, and line33 = $300 (withholding only)."""
    draft = _draft(
        line_items={"federal_tax": 0.0, "self_employment_tax": 0.0, "tax_withheld": 300.0,
                    "additional_child_tax_credit": 1700.0, "excess_social_security_tax": 500.0},
        totals={"total_tax": 0.0, "refund": 2500.0, "balance_owing": 0.0},
    )
    f = serialize_1040(draft, [], 2025)["ReturnData"]["IRS1040"]
    assert f["line28_additional_child_tax_credit"] == 1700.0
    assert f["line33_total_payments"] == 2500.0      # 300 + 1700 + 500
    assert f["line34_overpayment"] == 2500.0          # federal refund picks up ACTC + excess SS


def test_federal_refund_excludes_state_tax():
    """Refund/owe must be federal-only (line 33 − line 24), not the engine's
    combined federal+state position. Federal $8,000 + SE $2,000 = $10,000 tax,
    $11,000 withheld → federal refund $1,000 — even though $3,000 of state tax
    makes the combined engine result a $2,000 balance owing.

    FAILS before: line34/line37 pull the combined totals → owe $2,000, refund $0."""
    draft = _draft(
        line_items={"federal_tax": 8000.0, "self_employment_tax": 2000.0, "tax_withheld": 11000.0},
        totals={"total_tax": 13000.0, "refund": 0.0, "balance_owing": 2000.0},  # combined owes 2000
    )
    f = serialize_1040(draft, [], 2025)["ReturnData"]["IRS1040"]
    assert f["line24_total_tax"] == 10000.0
    assert f["line33_total_payments"] == 11000.0
    assert f["line34_overpayment"] == 1000.0
    assert f["line37_amount_you_owe"] == 0.0


def test_payments_refund_lines_reconcile():
    """Invariant: line34 = max(0, line33−line24), line37 = max(0, line24−line33),
    and the two are never both positive (the artifact internally reconciles)."""
    draft = _draft(
        line_items={"federal_tax": 8000.0, "self_employment_tax": 2000.0, "tax_withheld": 11000.0},
        totals={"total_tax": 13000.0, "refund": 0.0, "balance_owing": 2000.0},
    )
    f = serialize_1040(draft, [], 2025)["ReturnData"]["IRS1040"]
    l24, l33 = f["line24_total_tax"], f["line33_total_payments"]
    assert f["line34_overpayment"] == round(max(0.0, l33 - l24), 2)
    assert f["line37_amount_you_owe"] == round(max(0.0, l24 - l33), 2)
    assert f["line34_overpayment"] == 0.0 or f["line37_amount_you_owe"] == 0.0


def test_net_ptc_not_double_counted_in_payments():
    """The engine nets the Premium Tax Credit into federal_tax (line 24); it must
    NOT also be added to line 33 (payments) or the refund would be inflated. Here
    federal_tax already reflects a $2,000 PTC benefit, $3,000 withheld."""
    draft = _draft(
        line_items={"federal_tax": 3000.0, "self_employment_tax": 0.0, "tax_withheld": 3000.0,
                    "premium_tax_credit": 2000.0},
        totals={"total_tax": 3000.0, "refund": 0.0, "balance_owing": 0.0},
    )
    f = serialize_1040(draft, [], 2025)["ReturnData"]["IRS1040"]
    # line33 excludes PTC: 3000 withholding only → refund/owe both 0 (correct).
    assert f["line33_total_payments"] == 3000.0
    assert f["line34_overpayment"] == 0.0
    assert f["line37_amount_you_owe"] == 0.0


def test_slips_include_only_us_extracts():
    extracts = [
        FormExtract(form_code="W-2", jurisdiction="US", source_filename="w2.pdf", fields={"wages": 84000.0}),
        FormExtract(form_code="T4", jurisdiction="CA", source_filename="t4.pdf", fields={"employment_income": 1.0}),
        FormExtract(form_code="FORM-16", jurisdiction="IN", source_filename="f.pdf", fields={"gross_salary": 1.0}),
    ]
    slips = serialize_1040(_draft(), extracts, 2025)["ReturnData"]["Slips"]
    assert len(slips) == 1
    assert slips[0]["form_code"] == "W-2"
    assert slips[0]["fields"] == {"wages": 84000.0}


def test_missing_values_default_to_zero():
    f = serialize_1040(_draft(), [], 2025)["ReturnData"]["IRS1040"]
    assert f["line1a_wages"] == 0.0
    assert f["line24_total_tax"] == 0.0
    assert f["line11_agi"] == 0.0


def test_payload_is_json_serializable_and_keeps_false_flag():
    payload = serialize_1040(
        _draft(line_items={"wages": 84000.0}),
        [FormExtract(form_code="W-2", jurisdiction="US", source_filename="w2.pdf", fields={"wages": 84000.0})],
        2025,
        {"filing_status": "single", "num_dependents": "0"},
    )
    dumped = json.dumps(payload)
    assert '"transmissible": false' in dumped
    assert json.loads(dumped)["ReturnData"]["IRS1040"]["line1a_wages"] == 84000.0


def test_line33_includes_refundable_aotc():
    """The refundable American Opportunity Credit (Form 8863, 1040 line 29) is a
    payment. The engine credits education_credit_refundable in its balance, but the
    serializer previously dropped it from line 33 — understating the refund.

    $0 tax, $200 withheld, $1,000 refundable AOTC.

    FAILS before: line33 = $200 (withholding only); line34 = $200."""
    draft = _draft(
        line_items={"federal_tax": 0.0, "self_employment_tax": 0.0, "tax_withheld": 200.0,
                    "education_credit_refundable": 1000.0},
        totals={"total_tax": 0.0, "refund": 1200.0, "balance_owing": 0.0},
    )
    f = serialize_1040(draft, [], 2025)["ReturnData"]["IRS1040"]
    assert f["line29_refundable_education_credit"] == 1000.0
    assert f["line33_total_payments"] == 1200.0
    assert f["line34_overpayment"] == 1200.0


def test_line33_includes_additional_medicare_withheld():
    """W-2 box-6 additional-Medicare over-withholding (Form 8959 Part IV, Sch 3
    line 11) is a payment. The engine credits additional_medicare_tax_withheld in
    its balance; the serializer previously dropped it from line 33.

    $5,000 tax, $5,000 withheld, $450 additional-Medicare over-withheld.

    FAILS before: line33 = $5,000; line34 = $0 (the $450 refund vanished)."""
    draft = _draft(
        line_items={"federal_tax": 5000.0, "self_employment_tax": 0.0, "tax_withheld": 5000.0,
                    "additional_medicare_tax_withheld": 450.0},
        totals={"total_tax": 5000.0, "refund": 450.0, "balance_owing": 0.0},
    )
    f = serialize_1040(draft, [], 2025)["ReturnData"]["IRS1040"]
    assert f["line25c_additional_medicare_tax_withheld"] == 450.0
    assert f["line33_total_payments"] == 5450.0
    assert f["line34_overpayment"] == 450.0


def test_line33_sums_all_five_refundable_payment_items():
    """All five refundable items + withholding land in line 33:
    withholding $300 + ACTC $1,700 + excess SS $500 + addl-Medicare $120 +
    refundable AOTC $1,000 = $3,620."""
    draft = _draft(
        line_items={"federal_tax": 0.0, "self_employment_tax": 0.0, "tax_withheld": 300.0,
                    "additional_child_tax_credit": 1700.0, "excess_social_security_tax": 500.0,
                    "additional_medicare_tax_withheld": 120.0, "education_credit_refundable": 1000.0},
        totals={"total_tax": 0.0, "refund": 3620.0, "balance_owing": 0.0},
    )
    f = serialize_1040(draft, [], 2025)["ReturnData"]["IRS1040"]
    assert f["line33_total_payments"] == 3620.0
    assert f["line34_overpayment"] == 3620.0


def test_line33_reconciles_with_engine_refund_for_aotc_filer():
    """End-to-end: the artifact's federal refund must match the engine's computed
    refund for a refundable-AOTC filer (no state tax in play)."""
    draft = _draft(
        line_items={"federal_tax": 0.0, "self_employment_tax": 0.0, "tax_withheld": 200.0,
                    "education_credit_refundable": 1000.0},
        totals={"total_tax": 0.0, "refund": 1200.0, "balance_owing": 0.0},
    )
    f = serialize_1040(draft, [], 2025)["ReturnData"]["IRS1040"]
    assert f["line34_overpayment"] == draft.totals["refund"]


def test_line19_includes_credit_for_other_dependents():
    """Form 1040 line 19 = Child tax credit OR credit for other dependents (Sch 8812).
    The engine applies the ODC (it nets into federal_tax), but the serializer showed
    only the CTC — understating line 19 for filers with non-child dependents."""
    draft = _draft(
        line_items={"federal_tax": 4000.0, "credit_for_other_dependents": 500.0},
        credits={"child_tax_credit": 2000.0, "credit_for_other_dependents": 500.0},
    )
    f = serialize_1040(draft, [], 2025)["ReturnData"]["IRS1040"]
    assert f["line19_ctc_or_odc"] == 2500.0  # 2000 CTC + 500 ODC


def test_line20_surfaces_education_and_ptc_nonrefundable_credits():
    """The education non-refundable credit and net PTC reduce federal_tax in the
    engine but were entirely invisible in the artifact. Line 20 surfaces them."""
    draft = _draft(
        line_items={"federal_tax": 3000.0, "education_credit_nonrefundable": 1500.0,
                    "premium_tax_credit": 800.0},
    )
    f = serialize_1040(draft, [], 2025)["ReturnData"]["IRS1040"]
    assert f["line20_schedule3_nonrefundable_credits"] == 2300.0  # 1500 + 800


def test_line21_total_credits_sums_all_nonrefundable():
    draft = _draft(
        line_items={"federal_tax": 1000.0, "credit_for_other_dependents": 500.0,
                    "education_credit_nonrefundable": 1500.0, "premium_tax_credit": 800.0},
        credits={"child_tax_credit": 2000.0, "credit_for_other_dependents": 500.0},
    )
    f = serialize_1040(draft, [], 2025)["ReturnData"]["IRS1040"]
    # 2000 CTC + 500 ODC + 1500 education + 800 PTC = 4800
    assert f["line21_total_credits"] == 4800.0
    assert f["line21_total_credits"] == f["line19_ctc_or_odc"] + f["line20_schedule3_nonrefundable_credits"]


def test_no_credits_lines_are_zero_no_regression():
    f = serialize_1040(_draft(line_items={"federal_tax": 5000.0}), [], 2025)["ReturnData"]["IRS1040"]
    assert f["line19_ctc_or_odc"] == 0.0
    assert f["line20_schedule3_nonrefundable_credits"] == 0.0
    assert f["line21_total_credits"] == 0.0
