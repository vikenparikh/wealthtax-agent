"""CA Volunteer Firefighters' / Search-and-Rescue Volunteers' Amount.

Federal lines 31220 (VFA) / 31240 (SRVA), ITA s.118.06 / s.118.07: a volunteer
with 200+ eligible hours may claim a FIXED $3,000 amount, credited at the lowest
federal rate (15%) = $450. The $3,000 is non-indexed. A filer may claim the VFA
OR the SRVA but NOT both, so the combined eligible amount is capped at $3,000.
The 200-hour eligibility is the filer's responsibility. Previously the engine
ignored the claim.
"""
from wealthtax_agent.engines.ca_engine import compute_ca_return
from wealthtax_agent.state import FormExtract


def _t4(employment: float = 60000.0):
    return [FormExtract(form_code="T4", jurisdiction="CA", fields={"employment_income": employment})]


def test_volunteer_firefighter_amount_credit_is_450():
    base = compute_ca_return(_t4(), 2024, province="ON", user_answers={})
    d = compute_ca_return(_t4(), 2024, province="ON", user_answers={"volunteer_firefighter_amount": "3000"})
    # $3,000 x 15% lowest federal rate = $450 non-refundable credit.
    assert d.line_items["volunteer_amount_credit"] == 450.0
    assert round(base.line_items["federal_tax"] - d.line_items["federal_tax"], 2) == 450.0


def test_search_rescue_amount_credit_is_450():
    d = compute_ca_return(_t4(), 2024, province="ON", user_answers={"search_rescue_volunteer_amount": "3000"})
    assert d.line_items["volunteer_amount_credit"] == 450.0


def test_vfa_and_srva_cannot_both_be_claimed_combined_cap_3000():
    # A filer eligible for both may still claim only one $3,000 amount.
    d = compute_ca_return(_t4(), 2024, province="ON", user_answers={
        "volunteer_firefighter_amount": "3000",
        "search_rescue_volunteer_amount": "3000",
    })
    assert d.line_items["volunteer_amount_eligible"] == 3000.0
    assert d.line_items["volunteer_amount_credit"] == 450.0


def test_volunteer_amount_capped_at_3000():
    d = compute_ca_return(_t4(), 2024, province="ON", user_answers={"volunteer_firefighter_amount": "5000"})
    assert d.line_items["volunteer_amount_eligible"] == 3000.0
    assert d.line_items["volunteer_amount_credit"] == 450.0


def test_no_volunteer_amount_no_credit():
    d = compute_ca_return(_t4(), 2024, province="ON", user_answers={})
    assert d.line_items.get("volunteer_amount_credit", 0.0) == 0.0


def test_volunteer_amount_is_non_refundable():
    d = compute_ca_return(_t4(0.0), 2024, province="ON", user_answers={"volunteer_firefighter_amount": "3000"})
    assert d.line_items["federal_tax"] == 0.0
