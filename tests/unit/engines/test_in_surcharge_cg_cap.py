"""India surcharge is capped at 15% on the capital-gains tax portion.

The surcharge tier rate (10/15/25/37%) is set by total income, but a Finance Act
proviso caps the surcharge at 15% on the income-tax attributable to §111A/§112/§112A
capital gains. The engine previously applied the full tier rate to slab tax AND cg
tax together, over-charging high-income filers (>₹2cr) with capital gains.
"""
from wealthtax_agent.engines.in_engine import compute_in_return
from wealthtax_agent.state import FormExtract


def _form16(**fields):
    return FormExtract(form_code="FORM-16", jurisdiction="IN", fields=fields)


def _stock_gain(**fields):
    return FormExtract(form_code="STOCK-GAIN", jurisdiction="IN", fields=fields)


def test_cg_surcharge_capped_at_15pct_old_regime_37pct_tier():
    # ₹6cr salary (>₹5cr → 37% tier) + ₹50L LTCG-other (§112 20% → ₹10L cg tax).
    d = compute_in_return([_form16(gross_salary=60_000_000), _stock_gain(ltcg_other=5_000_000)],
                          year=2024, regime="old", user_answers={"age": "30"})
    slab = d.line_items["slab_tax"]
    cg = d.line_items["capital_gains_tax"]
    assert cg > 0
    # Surcharge: full 37% on slab, but only 15% on cg.
    assert d.line_items["surcharge"] == round(slab * 0.37 + cg * 0.15, 2)
    # ...which is strictly less than the old (buggy) full-rate-on-everything charge.
    assert d.line_items["surcharge"] < round((slab + cg) * 0.37, 2)


def test_cg_surcharge_cap_new_regime_25pct_tier():
    # ₹6cr salary new regime (tier capped at 25%) + ₹50L LTCG-other.
    d = compute_in_return([_form16(gross_salary=60_000_000), _stock_gain(ltcg_other=5_000_000)],
                          year=2024, regime="new", user_answers={"age": "30"})
    slab = d.line_items["slab_tax"]
    cg = d.line_items["capital_gains_tax"]
    assert cg > 0
    assert d.line_items["surcharge"] == round(slab * 0.25 + cg * 0.15, 2)


def test_cap_does_not_bite_below_25pct_tier():
    # ₹1.5cr income (>₹1cr, <₹2cr → 15% tier) + CG: cg_rate = min(0.15, 0.15) = 0.15
    # = tier rate, so the surcharge is unchanged (cap only bites at 25%/37%).
    d = compute_in_return([_form16(gross_salary=15_000_000), _stock_gain(ltcg_other=2_000_000)],
                          year=2024, regime="old", user_answers={"age": "30"})
    slab = d.line_items["slab_tax"]
    cg = d.line_items["capital_gains_tax"]
    assert cg > 0
    assert d.line_items["surcharge"] == round((slab + cg) * 0.15, 2)


def test_no_capital_gains_surcharge_unchanged_regression():
    # No CG → cg_tax 0 → surcharge = slab * tier rate, identical to before the fix.
    d = compute_in_return([_form16(gross_salary=60_000_000)],
                          year=2024, regime="old", user_answers={"age": "30"})
    assert d.line_items["capital_gains_tax"] == 0.0
    assert d.line_items["surcharge"] == round(d.line_items["slab_tax"] * 0.37, 2)


def test_2025_tables_also_cap_cg_surcharge():
    d = compute_in_return([_form16(gross_salary=60_000_000), _stock_gain(ltcg_other=5_000_000)],
                          year=2025, regime="old", user_answers={"age": "30"})
    slab = d.line_items["slab_tax"]
    cg = d.line_items["capital_gains_tax"]
    assert cg > 0
    assert d.line_items["surcharge"] == round(slab * 0.37 + cg * 0.15, 2)
