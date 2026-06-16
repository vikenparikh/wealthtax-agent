"""IN §80DDB — deduction for medical treatment of specified diseases.

Actual expense (net of reimbursement) capped at ₹40,000, or ₹1,00,000 when the patient
is a senior (60+). Old regime only (§115BAC disallows it), resident-only (NR barred,
RNOR keeps). The engine had no §80DDB, so a filer with treatment costs for cancer /
kidney failure / etc. was over-taxed.
"""
from wealthtax_agent.engines.in_engine import compute_in_return
from wealthtax_agent.state import FormExtract


def _f16(**fields):
    return FormExtract(form_code="FORM-16", jurisdiction="IN", fields=fields)


def _draft(age="40", amount="50000", regime="old", residency_status="ROR"):
    return compute_in_return([_f16(gross_salary=1200000)], year=2024, regime=regime,
                             user_answers={"age": age, "section_80ddb_medical": amount},
                             residency_status=residency_status)


def test_under_60_capped_at_40k():
    assert _draft(age="40", amount="50000").line_items["section_80ddb"] == 40000.0


def test_senior_capped_at_100k():
    assert _draft(age="65", amount="150000").line_items["section_80ddb"] == 100000.0


def test_actual_expense_below_cap():
    assert _draft(age="40", amount="30000").line_items["section_80ddb"] == 30000.0


def test_reduces_taxable_income():
    base = compute_in_return([_f16(gross_salary=1200000)], year=2024, regime="old",
                             user_answers={"age": "40"})
    with_d = _draft(age="40", amount="50000")
    assert round(base.totals["taxable_income"] - with_d.totals["taxable_income"], 2) == 40000.0


def test_disallowed_in_new_regime():
    assert _draft(regime="new", amount="50000").line_items["section_80ddb"] == 0.0


def test_nr_barred_rnor_allowed():
    assert _draft(residency_status="NR", amount="50000").line_items["section_80ddb"] == 0.0
    assert _draft(residency_status="RNOR", amount="50000").line_items["section_80ddb"] == 40000.0


def test_no_expense_zero():
    d = compute_in_return([_f16(gross_salary=1200000)], year=2024, regime="old",
                          user_answers={"age": "40"})
    assert d.line_items["section_80ddb"] == 0.0
