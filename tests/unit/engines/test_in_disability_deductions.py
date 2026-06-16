"""IN §80U (own disability) + §80DD (dependent disability) flat deductions.

Flat ₹75,000 (disability ≥40%) / ₹1,25,000 (severe ≥80%), independent of expense.
Old regime only (§115BAC disallows them) and resident-only (NR barred; RNOR keeps).
§80U and §80DD are distinct sections, both claimable in the same year.
"""
from wealthtax_agent.engines.in_engine import compute_in_return
from wealthtax_agent.state import FormExtract


def _f16(**fields):
    return FormExtract(form_code="FORM-16", jurisdiction="IN", fields=fields)


def _draft(regime="old", residency_status="ROR", **answers):
    ua = {"age": "30"}
    ua.update(answers)
    return compute_in_return([_f16(gross_salary=1200000)], year=2024, regime=regime,
                             user_answers=ua, residency_status=residency_status)


def test_80u_normal_disability():
    d = _draft(taxpayer_disability="normal")
    assert d.line_items["section_80u"] == 75000.0


def test_80u_severe_disability():
    d = _draft(taxpayer_disability="severe")
    assert d.line_items["section_80u"] == 125000.0


def test_80dd_dependent_disability():
    d = _draft(dependent_disability="severe")
    assert d.line_items["section_80dd"] == 125000.0


def test_80u_and_80dd_both_claimable():
    # Distinct sections — both in the same year is correct, not a double-count.
    d = _draft(taxpayer_disability="normal", dependent_disability="severe")
    assert d.line_items["section_80u"] == 75000.0
    assert d.line_items["section_80dd"] == 125000.0


def test_reduces_taxable_income_by_deduction():
    base = _draft()
    with_d = _draft(taxpayer_disability="severe")
    assert round(base.totals["taxable_income"] - with_d.totals["taxable_income"], 2) == 125000.0


def test_disallowed_in_new_regime():
    d = _draft(regime="new", taxpayer_disability="severe", dependent_disability="severe")
    assert d.line_items["section_80u"] == 0.0
    assert d.line_items["section_80dd"] == 0.0


def test_nr_barred_rnor_allowed():
    nr = _draft(residency_status="NR", taxpayer_disability="severe")
    assert nr.line_items["section_80u"] == 0.0
    rnor = _draft(residency_status="RNOR", taxpayer_disability="severe")
    assert rnor.line_items["section_80u"] == 125000.0  # RNOR is resident → keeps it


def test_none_or_absent_flag_zero():
    assert _draft(taxpayer_disability="none").line_items["section_80u"] == 0.0
    assert _draft().line_items["section_80u"] == 0.0  # absent → 0


def test_80gg_base_reduced_by_disability_deduction():
    # §80GG's adjusted-total-income must net the §80U/§80DD deductions. A no-HRA
    # renter with a disability deduction → §80GG computed on the lower base.
    no_disab = _draft(annual_rent_paid="240000")  # no HRA → §80GG applies
    with_disab = _draft(annual_rent_paid="240000", taxpayer_disability="severe")
    # Both have §80GG; with the disability deduction the §80GG base is lower, so the
    # 25%-of-income / rent-minus-10% limbs shift — §80GG must be <= the no-disab case.
    assert with_disab.line_items["section_80gg"] <= no_disab.line_items["section_80gg"]
    assert with_disab.line_items["section_80u"] == 125000.0
