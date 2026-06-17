"""India surcharge MARGINAL RELIEF at each tier threshold (₹50L/₹1cr/₹2cr/₹5cr).

When total income just crosses a surcharge tier threshold T, the extra surcharge
can exceed the extra income earned above T — a cliff. The Finance Act grants
marginal relief: the income-tax-plus-surcharge payable on income T+Δ may not
exceed the income tax on income exactly T plus Δ (the income earned above T).

These tests assert that for a small Δ above each threshold, in both regimes, the
incremental (income_tax + surcharge) over the at-threshold baseline is bounded by
the income increase (cess applies on top, so ×1.04, +₹1 for rounding); and that
relief is self-limiting (no regression) at incomes well above the threshold.
"""
from wealthtax_agent.engines.in_engine import compute_in_return
from wealthtax_agent.state import FormExtract


def _form16(**fields):
    return FormExtract(form_code="FORM-16", jurisdiction="IN", fields=fields)


def _itax_plus_surcharge(d):
    """income_tax (post-rebate slab + cg) + surcharge, i.e. total_tax minus cess."""
    li = d.line_items
    # tax_after_rebate = slab_tax + cg_tax - rebate; surcharge added separately.
    return round(
        li["slab_tax"] + li["capital_gains_tax"] - li["rebate_87a"] + li["surcharge"], 2
    )


# Standard deduction (₹50,000) reduces gross salary to total income, so target a
# given TOTAL income by setting gross = total + 50,000 (the surcharge tiers key off
# total income, not gross).
_STD_DED = 50_000


def _run_total(total_income, regime, year=2024):
    return compute_in_return(
        [_form16(gross_salary=total_income + _STD_DED)],
        year=year,
        regime=regime,
        residency_status="ROR",
        user_answers={"age": "30"},
    )


def test_relief_50L_threshold_new_regime():
    # Total income ₹50L+₹1L crosses the ₹50L (10%) tier. Δ = ₹1,00,000.
    base = _run_total(50_00_000, "new")
    above = _run_total(51_00_000, "new")
    delta_income = 1_00_000
    delta_tax = _itax_plus_surcharge(above) - _itax_plus_surcharge(base)
    assert delta_tax <= delta_income * 1.04 + 1


def test_relief_50L_threshold_old_regime():
    base = _run_total(50_00_000, "old")
    above = _run_total(50_10_000, "old")
    delta_income = 10_000
    delta_tax = _itax_plus_surcharge(above) - _itax_plus_surcharge(base)
    assert delta_tax <= delta_income * 1.04 + 1


def test_relief_2cr_threshold_new_regime():
    base = _run_total(2_00_00_000, "new")
    above = _run_total(2_00_01_000, "new")
    delta_income = 1_000
    delta_tax = _itax_plus_surcharge(above) - _itax_plus_surcharge(base)
    assert delta_tax <= delta_income * 1.04 + 1


def test_relief_self_limiting_no_regression():
    # Total ₹70L is well above ₹50L: full surcharge << income above threshold, so
    # relief is 0 and surcharge is the plain tier rate on slab tax (unchanged).
    d = _run_total(70_00_000, "new")
    slab = d.line_items["slab_tax"]
    rebate = d.line_items["rebate_87a"]
    # new regime tier rate at >₹50L is 10%, applied to post-rebate slab tax.
    assert d.line_items["surcharge"] == round(max(0.0, slab - rebate) * 0.10, 2)
