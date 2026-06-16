"""CA Home Buyers' Amount — federal non-refundable credit (line 31270).

Income Tax Act (Canada) s.118.05: a first-time home buyer may claim a FIXED
$10,000 amount, credited at the lowest federal rate (15%) = $1,500 maximum.
The $10,000 amount has been flat (non-indexed) since the 2022 federal budget
raised it from $5,000. Previously the engine ignored the claim entirely.
"""
from wealthtax_agent.engines.ca_engine import compute_ca_return
from wealthtax_agent.state import FormExtract


def _t4(employment: float = 80000.0):
    return [FormExtract(form_code="T4", jurisdiction="CA", fields={"employment_income": employment})]


def test_home_buyers_amount_credit_is_1500_at_full_claim():
    base = compute_ca_return(_t4(), 2024, province="ON", user_answers={})
    d = compute_ca_return(_t4(), 2024, province="ON", user_answers={"home_buyers_amount": "10000"})
    # $10,000 x 15% lowest federal rate = $1,500 non-refundable credit.
    assert d.line_items["home_buyers_credit"] == 1500.0
    # Bottom line moves: federal tax drops by exactly the credit.
    assert round(base.line_items["federal_tax"] - d.line_items["federal_tax"], 2) == 1500.0


def test_home_buyers_amount_capped_at_10000():
    d = compute_ca_return(_t4(), 2024, province="ON", user_answers={"home_buyers_amount": "15000"})
    assert d.line_items["home_buyers_eligible"] == 10000.0
    assert d.line_items["home_buyers_credit"] == 1500.0  # cap holds
    assert any("exceeds $10,000 cap" in n for n in d.notes)


def test_partial_home_buyers_amount_credited_proportionally():
    # A spouse splitting the claim may allocate less than the full $10,000.
    d = compute_ca_return(_t4(), 2024, province="ON", user_answers={"home_buyers_amount": "4000"})
    assert d.line_items["home_buyers_eligible"] == 4000.0
    assert d.line_items["home_buyers_credit"] == 600.0  # 4000 x 0.15


def test_no_home_buyers_amount_no_credit():
    d = compute_ca_return(_t4(), 2024, province="ON", user_answers={})
    assert d.line_items.get("home_buyers_credit", 0.0) == 0.0


def test_home_buyers_amount_is_non_refundable():
    # Zero-tax filer: the credit cannot create a refund beyond zeroing tax.
    d = compute_ca_return(_t4(0.0), 2024, province="ON", user_answers={"home_buyers_amount": "10000"})
    assert d.line_items["federal_tax"] == 0.0
