"""tests/test_estimated_tax.py — unit tests for estimated-tax safe-harbour calculator."""

from __future__ import annotations

import pytest

from wealthtax_agent.engines.estimated_tax import compute_estimated_payments, EstimatedTaxResult


class TestBasicComputation:
    def test_returns_result_type(self):
        r = compute_estimated_payments(tax_year=2025)
        assert isinstance(r, EstimatedTaxResult)

    def test_zero_income_no_payment(self):
        r = compute_estimated_payments(tax_year=2025, prior_year_tax=0.0)
        assert r.recommended_annual == 0.0
        for q, amt in r.quarterly_payments.items():
            assert amt == 0.0, f"{q} should be $0"

    def test_four_quarters_always_present(self):
        r = compute_estimated_payments(tax_year=2025, w2_wages=100_000)
        assert set(r.quarterly_payments.keys()) == {"Q1", "Q2", "Q3", "Q4"}
        assert set(r.quarterly_due_dates.keys()) == {"Q1", "Q2", "Q3", "Q4"}

    def test_q4_due_date_is_next_year(self):
        r = compute_estimated_payments(tax_year=2025)
        assert r.quarterly_due_dates["Q4"].startswith("2026")

    def test_q1_q2_q3_due_dates_in_tax_year(self):
        r = compute_estimated_payments(tax_year=2025)
        for q in ("Q1", "Q2", "Q3"):
            assert r.quarterly_due_dates[q].startswith("2025")

    def test_equal_quarterly_amounts(self):
        r = compute_estimated_payments(
            tax_year=2025, prior_year_tax=20_000, w2_wages=150_000
        )
        amounts = list(r.quarterly_payments.values())
        assert len(set(amounts)) == 1, "All quarters should be equal"

    def test_withholding_reduces_payment(self):
        # Use same income so safe_harbour_a (prior-year method) dominates
        common = dict(tax_year=2025, prior_year_tax=10_000, short_term_gains=50_000)
        r_no_wh = compute_estimated_payments(**common, withholding_ytd=0.0)
        r_with_wh = compute_estimated_payments(**common, withholding_ytd=6_000)
        assert r_with_wh.quarterly_payments["Q1"] < r_no_wh.quarterly_payments["Q1"]

    def test_high_prior_year_agi_triggers_110pct(self):
        """Prior-year AGI > $150 000 should use 110% safe-harbour."""
        r = compute_estimated_payments(
            tax_year=2025,
            prior_year_tax=50_000,
            prior_year_agi=200_000,
        )
        assert r.safe_harbour_a == pytest.approx(55_000.0, rel=1e-4)

    def test_low_prior_year_agi_uses_100pct(self):
        r = compute_estimated_payments(
            tax_year=2025,
            prior_year_tax=10_000,
            prior_year_agi=100_000,
        )
        assert r.safe_harbour_a == pytest.approx(10_000.0, rel=1e-4)

    def test_note_includes_draft_disclaimer(self):
        r = compute_estimated_payments(tax_year=2025, prior_year_tax=5_000)
        assert "DRAFT" in r.note


class TestSafeHarbourLogic:
    def test_recommends_lower_of_a_and_b(self):
        """recommended_annual = min(safe_harbour_a, safe_harbour_b)."""
        r = compute_estimated_payments(
            tax_year=2025,
            prior_year_tax=30_000,
            w2_wages=200_000,
            short_term_gains=50_000,
        )
        assert r.recommended_annual == pytest.approx(
            min(r.safe_harbour_a, r.safe_harbour_b), rel=1e-4
        )

    def test_safe_harbour_b_is_90pct_current(self):
        r = compute_estimated_payments(
            tax_year=2025,
            w2_wages=100_000,
            prior_year_tax=20_000,
        )
        assert r.safe_harbour_b == pytest.approx(r.estimated_annual_tax * 0.90, rel=1e-3)


class TestDayTraderScenario:
    """Realistic scenario: QQQ day trader with short-term gains."""

    def test_day_trader_owes_quarterly_payments(self):
        r = compute_estimated_payments(
            tax_year=2025,
            short_term_gains=150_000,   # QQQ day-trading P&L
            w2_wages=0.0,
            withholding_ytd=0.0,
            prior_year_tax=30_000,
            prior_year_agi=180_000,
        )
        # High prior-year AGI → 110% safe harbour
        assert r.safe_harbour_a == pytest.approx(33_000.0, rel=1e-3)
        # Each quarter > 0
        for q, amt in r.quarterly_payments.items():
            assert amt > 0, f"{q} should be positive for a day trader"

    def test_se_tax_included_in_estimate(self):
        r = compute_estimated_payments(
            tax_year=2025,
            se_net_profit=80_000,
        )
        # SE tax at 15.3% on $80 000 ≈ $12 240
        # Estimated annual should exceed ordinary income tax alone
        assert r.estimated_annual_tax > 80_000 * 0.22  # at minimum 22% bracket

    def test_negative_recommended_when_withholding_exceeds(self):
        r = compute_estimated_payments(
            tax_year=2025,
            prior_year_tax=10_000,
            withholding_ytd=50_000,  # massive W-2 withholding → no payments needed
        )
        # net_needed = max(0, recommended - withholding) → 0
        for q, amt in r.quarterly_payments.items():
            assert amt == 0.0
