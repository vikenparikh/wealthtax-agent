"""Edge branches of engines/estimated_tax.py not covered by test_estimated_tax.py.

Found via a fan-out audit subagent; every expected value below was confirmed
by running the implementation read-only. Covers the progressive-tax zero/
negative guard and top 37% bracket, the safe-harbour-B-wins selection, the
per-quarter rounding residual, and the LTCG 0% band.
"""

from wealthtax_agent.engines.estimated_tax import (
    _ORDINARY_BRACKETS_SINGLE_2024,
    _estimate_federal_tax,
    _progressive_tax,
    compute_estimated_payments,
)


def test_progressive_tax_zero_and_negative_income():
    assert _progressive_tax(0.0, _ORDINARY_BRACKETS_SINGLE_2024) == 0.0
    assert _progressive_tax(-100.0, _ORDINARY_BRACKETS_SINGLE_2024) == 0.0


def test_progressive_tax_reaches_top_37_percent_bracket():
    assert _progressive_tax(700000.0, _ORDINARY_BRACKETS_SINGLE_2024) == 217187.75


def test_safe_harbour_b_wins_when_prior_year_tax_is_huge():
    r = compute_estimated_payments(2025, w2_wages=50000, prior_year_tax=999999)
    assert r.safe_harbour_a == 999999.0
    assert r.recommended_annual == r.safe_harbour_b == 3614.4  # 90% current < 100% prior
    assert r.recommended_annual < r.safe_harbour_a


def test_quarterly_payments_can_under_sum_recommended_by_a_cent():
    # round(2500.125, 2) -> 2500.12 (banker's rounding), so 4 quarters = 10000.48.
    r = compute_estimated_payments(2025, w2_wages=500000, prior_year_tax=10000.50, prior_year_agi=0)
    assert r.recommended_annual == 10000.50
    assert all(q == 2500.12 for q in r.quarterly_payments.values())
    assert round(sum(r.quarterly_payments.values()), 2) == 10000.48


def test_estimate_federal_tax_ltcg_fully_in_zero_percent_band():
    # AGI 50000 of LTCG only: after the standard deduction the LTCG sits in the
    # 0% capital-gains band, so total federal tax is 0.
    assert _estimate_federal_tax(0, 0, 0, 50000, 0) == 0.0


def test_estimate_federal_tax_ltcg_taxed_above_ordinary_floor():
    # With 200k ordinary income beneath it, the same 50k LTCG is no longer 0%.
    assert _estimate_federal_tax(0, 0, 0, 50000, 200000) == 45038.5
