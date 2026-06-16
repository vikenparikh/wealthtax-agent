"""IN §80EEB — deduction for interest on an electric-vehicle loan.

Interest on an EV loan, capped at ₹1,50,000/year. Old regime only (§115BAC disallows
it), resident-only (NR barred, RNOR keeps). The engine had no §80EEB, so an EV buyer
paying loan interest was over-taxed.
"""
from wealthtax_agent.engines.in_engine import compute_in_return
from wealthtax_agent.state import FormExtract


def _f16(**fields):
    return FormExtract(form_code="FORM-16", jurisdiction="IN", fields=fields)


def _draft(interest="200000", regime="old", residency_status="ROR"):
    return compute_in_return([_f16(gross_salary=1500000)], year=2024, regime=regime,
                             user_answers={"age": "40", "section_80eeb_ev_loan_interest": interest},
                             residency_status=residency_status)


def test_capped_at_150k():
    assert _draft(interest="200000").line_items["section_80eeb"] == 150000.0


def test_actual_interest_below_cap():
    assert _draft(interest="80000").line_items["section_80eeb"] == 80000.0


def test_reduces_taxable_income():
    base = compute_in_return([_f16(gross_salary=1500000)], year=2024, regime="old",
                             user_answers={"age": "40"})
    with_d = _draft(interest="80000")
    assert round(base.totals["taxable_income"] - with_d.totals["taxable_income"], 2) == 80000.0


def test_disallowed_in_new_regime():
    assert _draft(regime="new", interest="200000").line_items["section_80eeb"] == 0.0


def test_nr_barred_rnor_allowed():
    assert _draft(residency_status="NR", interest="200000").line_items["section_80eeb"] == 0.0
    assert _draft(residency_status="RNOR", interest="200000").line_items["section_80eeb"] == 150000.0


def test_no_interest_zero():
    d = compute_in_return([_f16(gross_salary=1500000)], year=2024, regime="old",
                          user_answers={"age": "40"})
    assert d.line_items["section_80eeb"] == 0.0
