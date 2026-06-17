"""CA Multigenerational Home Renovation Tax Credit (MHRTC) — line 45355.

Income Tax Act s.122.92 (effective 2023): a REFUNDABLE credit of 15% of
eligible renovation expenditures to build a secondary self-contained dwelling
unit for a senior (65+) or a Disability-Tax-Credit-eligible adult relative,
capped at $50,000 of expenditure → max $7,500. The 15% rate and $50,000 cap are
fixed (non-indexed). Being refundable, it pays out even to a zero-tax filer.
Previously the engine ignored the input.
"""
from wealthtax_agent.engines.ca_engine import compute_ca_return
from wealthtax_agent.state import FormExtract


def _t4(employment: float = 90000.0, withheld: float = 25000.0):
    return [FormExtract(form_code="T4", jurisdiction="CA",
                        fields={"employment_income": employment, "income_tax_deducted": withheld})]


def test_mhrtc_increases_refund_by_15pct_of_expenditure():
    base = compute_ca_return(_t4(), 2024, province="ON", user_answers={})
    d = compute_ca_return(_t4(), 2024, province="ON", user_answers={"mhrtc_qualifying_expenditure": "50000"})
    # 15% x $50,000 = $7,500 refundable.
    assert d.line_items["mhrtc_credit"] == 7500.0
    assert round(d.estimated_refund - base.estimated_refund, 2) == 7500.0


def test_mhrtc_caps_at_50000_expenditure():
    d = compute_ca_return(_t4(), 2024, province="ON", user_answers={"mhrtc_qualifying_expenditure": "80000"})
    # 15% of the capped $50,000 = $7,500 (not 15% of $80,000 = $12,000).
    assert d.line_items["mhrtc_credit"] == 7500.0


def test_mhrtc_partial_expenditure():
    d = compute_ca_return(_t4(), 2024, province="ON", user_answers={"mhrtc_qualifying_expenditure": "20000"})
    assert d.line_items["mhrtc_credit"] == 3000.0  # 15% x 20000


def test_mhrtc_is_refundable_for_zero_tax_filer():
    # Low income, no withholding -> ~$0 tax: the refundable credit still pays out.
    d = compute_ca_return(_t4(15000.0, 0.0), 2024, province="ON",
                          user_answers={"mhrtc_qualifying_expenditure": "50000"})
    assert d.estimated_refund >= 7500.0


def test_no_mhrtc_input_no_credit():
    d = compute_ca_return(_t4(), 2024, province="ON", user_answers={})
    assert d.line_items.get("mhrtc_credit", 0.0) == 0.0


def test_mhrtc_denied_for_non_resident():
    d = compute_ca_return(_t4(), 2024, province="ON",
                          user_answers={"mhrtc_qualifying_expenditure": "50000"},
                          residency_status="non_resident")
    assert d.line_items.get("mhrtc_credit", 0.0) == 0.0
