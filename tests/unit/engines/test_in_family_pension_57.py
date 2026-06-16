"""§57(iia) standard deduction on family pension (Income from Other Sources).

Family pension (paid to the legal heir of a deceased employee) is taxed under Other
Sources, with a standard deduction of the lower of 1/3 of the pension or a statutory
cap (₹15,000 old regime; ₹25,000 new regime from AY 2025-26). §115BAC does NOT
disallow it, so it applies under BOTH regimes — only the cap value differs. Before
this fix the engine had no family-pension handling, over-taxing widows/dependants.
"""
from wealthtax_agent.engines.in_engine import compute_in_return
from wealthtax_agent.state import FormExtract


def _form16(**fields):
    return FormExtract(form_code="FORM-16", jurisdiction="IN", fields=fields)


def _draft(year, regime, **answers):
    ua = {"age": "30"}
    ua.update(answers)
    return compute_in_return([], year=year, regime=regime, user_answers=ua)


def test_new_regime_cap_25k_ay2025():
    # ₹90,000 family pension: 1/3 = 30,000 > 25,000 cap → deduction 25,000.
    d = _draft(2025, "new", family_pension_income="90000")
    assert d.line_items["family_pension"] == 90000.0
    assert d.line_items["family_pension_deduction"] == 25000.0
    assert d.line_items["family_pension_taxable"] == 65000.0


def test_old_regime_cap_15k():
    # ₹90,000: 1/3 = 30,000 > 15,000 old cap → deduction 15,000.
    d = _draft(2025, "old", family_pension_income="90000")
    assert d.line_items["family_pension_deduction"] == 15000.0
    assert d.line_items["family_pension_taxable"] == 75000.0


def test_one_third_fraction_binds_when_below_cap():
    # ₹30,000: 1/3 = 10,000 < cap → deduction 10,000 (fraction binds).
    d = _draft(2025, "new", family_pension_income="30000")
    assert d.line_items["family_pension_deduction"] == 10000.0
    assert d.line_items["family_pension_taxable"] == 20000.0


def test_2024_new_regime_cap_still_15k():
    # AY 2024-25: the ₹25,000 new-regime bump has not started yet → cap 15,000.
    d = _draft(2024, "new", family_pension_income="90000")
    assert d.line_items["family_pension_deduction"] == 15000.0
    assert d.line_items["family_pension_taxable"] == 75000.0


def test_no_family_pension_zero_and_no_total_income_change():
    base = _draft(2025, "new")
    with_fp = _draft(2025, "new", family_pension_income="0")
    assert with_fp.line_items["family_pension_deduction"] == 0.0
    assert with_fp.line_items["family_pension"] == 0.0
    assert with_fp.totals["total_income"] == base.totals["total_income"]


def test_taxable_family_pension_enters_total_income_net_of_deduction():
    # The NET (after §57 deduction), not the gross, must reach total income.
    base = _draft(2025, "new")
    with_fp = _draft(2025, "new", family_pension_income="90000")
    delta = with_fp.totals["total_income"] - base.totals["total_income"]
    assert round(delta, 2) == 65000.0  # 90,000 - 25,000 deduction
