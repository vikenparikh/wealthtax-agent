"""Verify residency tests match published IRS / CRA / India rules."""

import pytest

from wealthtax_agent.engines.residency import (
    ca_residency,
    india_residency,
    recommend_residency,
    us_residency,
    us_substantial_presence,
)


# ---------- US Substantial Presence ----------

def test_spt_zero_when_under_31_days():
    assert us_substantial_presence(15, 0, 0) is False


def test_spt_passes_with_183_current_alone():
    assert us_substantial_presence(183, 0, 0) is True


def test_spt_passes_with_120_current_and_prior_history():
    """120 + 120/3 + 120/6 = 120 + 40 + 20 = 180 → fails (need 183)."""
    assert us_substantial_presence(120, 120, 120) is False
    # Bump current by 3 days → 123 + 40 + 20 = 183 exactly
    assert us_substantial_presence(123, 120, 120) is True


def test_spt_irs_example_one_hundred_days_each_year():
    """IRS example: 100 days * 3 → 100 + 33.33 + 16.66 = 149.99, fails."""
    assert us_substantial_presence(100, 100, 100) is False


def test_us_citizen_always_resident():
    assert us_residency(0, is_us_citizen=True) == "resident"


def test_us_green_card_always_resident():
    assert us_residency(0, is_green_card=True) == "resident"


def test_us_dual_status_when_moved():
    """Moved + SPT met → dual-status year."""
    assert us_residency(200, moved_in_or_out=True) == "dual_status"


def test_us_nonresident_when_short_stay():
    assert us_residency(150) == "nonresident"


# ---------- Canada ----------

def test_ca_primary_ties_makes_resident():
    assert ca_residency(50, has_primary_ties=True) == "resident"


def test_ca_primary_ties_with_move_part_year():
    assert ca_residency(180, has_primary_ties=True, moved_in_or_out=True) == "part_year_resident"


def test_ca_deemed_resident_at_183():
    assert ca_residency(183) == "resident"


def test_ca_nonresident_when_short_no_ties():
    assert ca_residency(100) == "non_resident"


# ---------- India ----------

def test_india_ror_long_stay_with_history():
    """200 days current + 800 days in last 7 → ROR."""
    assert india_residency(200, 400, days_prior_7_resident_years=800) == "ROR"


def test_india_rnor_when_history_insufficient():
    """200 days current but only 500 days in last 7 → RNOR."""
    assert india_residency(200, 400, days_prior_7_resident_years=500) == "RNOR"


def test_india_nr_when_under_60_days_current():
    assert india_residency(30, 400) == "NR"


def test_india_resident_via_60_plus_365_in_4_yrs():
    """65 days current + 400 days in prior 4 → resident."""
    assert india_residency(65, 400) == "RNOR"  # but no 730-day history → RNOR


def test_india_nri_visitor_relaxed_to_182_days():
    """Indian-citizen NRI visiting with Indian income ≤ 15L: 60-day rule relaxed to 182."""
    # 100 days current + 400 prior, NRI status → NR (because relaxed threshold is 182)
    assert india_residency(100, 400, is_indian_citizen=True, indian_income_above_15l=False) == "NR"


def test_india_deemed_residency_indian_citizen_high_income():
    """Indian citizen with > ₹15L income, no other-country tax: deemed RNOR."""
    assert india_residency(100, 0, is_indian_citizen=True, indian_income_above_15l=True) == "RNOR"


# ---------- Orchestrator + treaty hints ----------

def test_recommend_residency_us_only():
    result = recommend_residency({"US": 200})
    assert result["status"]["US"] == "resident"


def test_recommend_residency_us_plus_india_emits_treaty_hint():
    result = recommend_residency(
        {"US": 200, "IN": 200},
        prior_year_days={"IN": {"prior_4_total": 400}},
    )
    # Both resident-like → US-India treaty hint
    assert any("US-India" in note for note in result["notes"])


def test_recommend_residency_ca_plus_us_emits_treaty_hint():
    result = recommend_residency(
        {"US": 200, "CA": 200},
        user_answers={"has_primary_ties_ca": "yes"},
    )
    assert any("US-Canada" in note for note in result["notes"])


def test_recommend_residency_single_jurisdiction_no_treaty_hint():
    result = recommend_residency({"US": 100, "IN": 50, "CA": 200})
    treaty_notes = [n for n in result["notes"] if "treaty" in n.lower()]
    # Only CA is resident-like (US is nonresident at 100 days, IN at 50 is NR)
    assert treaty_notes == []


def test_recommend_residency_includes_threshold_proximity_warning():
    """Within ±10 of 183-day threshold → warning surfaces."""
    result = recommend_residency({"US": 180})
    assert any("threshold" in note.lower() for note in result["notes"])


# --- §6(6) ROR requires BOTH 730-days-in-7 AND resident in 2 of last 10 years ---

def test_india_ror_requires_two_of_ten_resident_years():
    """A returning NRI present >= 730 days in the last 7 years but resident in
    only 1 of the last 10 years is RNOR, not ROR (§6(6) needs both conditions).
    Misclassifying them as ROR would wrongly tax their foreign income."""
    assert india_residency(200, 400, days_prior_7_resident_years=800,
                           resident_years_in_last_10=1) == "RNOR"
    # both conditions satisfied -> ROR
    assert india_residency(200, 400, days_prior_7_resident_years=800,
                           resident_years_in_last_10=5) == "ROR"


def test_india_ror_default_preserves_730_day_behaviour():
    """Default resident_years_in_last_10=2 keeps the prior behaviour when the
    caller supplies no count."""
    assert india_residency(200, 400, days_prior_7_resident_years=800) == "ROR"


def test_recommend_residency_returning_nri_classified_rnor():
    """End-to-end through the orchestrator: a returning NRI (lots of recent days
    but resident in only 1 of last 10 years) is RNOR."""
    result = recommend_residency(
        {"IN": 200},
        prior_year_days={"IN": {"prior_4_total": 400, "prior_7_days": 800}},
        user_answers={"india_resident_years_in_last_10": "1"},
    )
    assert result["status"]["IN"] == "RNOR"
