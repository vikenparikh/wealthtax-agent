"""US residential energy credits (Form 5695) — §25D + §25C.

§25D Residential Clean Energy Credit: 30% of qualified clean-energy cost
(solar/wind/geothermal/battery), NO dollar cap, non-refundable (excess carries
forward). §25C Energy Efficient Home Improvement Credit: 30% of cost with a
FIXED $1,200 general annual cap plus a SEPARATE $2,000 annual cap for heat
pumps / heat-pump water heaters / biomass. Both rates and caps are fixed by the
IRA-2022 through 2032 (non-indexed). Previously the engine ignored these inputs
entirely — a solar/heat-pump filer lost up to $6,000+ of credit.
"""
from wealthtax_agent.engines.us_engine import compute_us_return
from wealthtax_agent.state import FormExtract


def _w2(wages: float = 90000.0):
    return [FormExtract(form_code="W-2", jurisdiction="US", fields={"wages": wages})]


def test_section_25d_clean_energy_30pct_no_cap():
    base = compute_us_return(_w2(), 2024, user_answers={})
    d = compute_us_return(_w2(), 2024, user_answers={"residential_clean_energy_cost": "20000"})
    # 30% of $20,000 = $6,000, no cap.
    assert d.line_items["residential_clean_energy_credit"] == 6000.0
    # Non-refundable: federal_tax drops by exactly the credit (tax exceeds it).
    assert round(base.line_items["federal_tax"] - d.line_items["federal_tax"], 2) == 6000.0


def test_section_25c_general_cap_binds():
    d = compute_us_return(_w2(), 2024, user_answers={"energy_efficient_improvements": "10000"})
    # 30% of $10,000 = $3,000 but the general annual cap is $1,200.
    assert d.line_items["energy_efficient_home_credit"] == 1200.0


def test_section_25c_heat_pump_has_separate_cap():
    d = compute_us_return(_w2(), 2024, user_answers={
        "energy_efficient_improvements": "1000",  # 30% -> 300 (under $1,200)
        "heat_pump_cost": "8000",                 # 30% -> 2400, capped at $2,000
    })
    # General $300 + heat-pump $2,000 = $2,300 (two independent caps).
    assert d.line_items["energy_efficient_home_credit"] == 2300.0


def test_no_energy_inputs_no_credit_no_regression():
    d = compute_us_return(_w2(), 2024, user_answers={})
    assert d.line_items.get("residential_clean_energy_credit", 0.0) == 0.0
    assert d.line_items.get("energy_efficient_home_credit", 0.0) == 0.0


def test_energy_credits_are_non_refundable():
    # Low income, tiny tax: the credit cannot create a refund beyond zeroing tax.
    d = compute_us_return(_w2(15000.0), 2024, user_answers={"residential_clean_energy_cost": "20000"})
    assert d.line_items["federal_tax"] == 0.0
    # The full computed credit is still reported (excess would carry forward).
    assert d.line_items["residential_clean_energy_credit"] == 6000.0
