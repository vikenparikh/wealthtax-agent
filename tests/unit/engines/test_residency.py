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


# ---------- US SPT — oracle + boundary pins ----------
#
# The four example tests above all use EQUAL priors (120,120,120 / 100,100,100),
# so they provably cannot catch a /3 <-> /6 divisor swap (120/3 + 120/6 ==
# 120/6 + 120/3) nor exact-fraction-vs-truncation. SPT decides US resident vs
# nonresident — i.e. WHICH tax engine runs for the filer — so a wrong divisor,
# threshold, or rounding here mis-taxes a whole population. These pins close that
# gap: an independent oracle across a grid with ASYMMETRIC priors, plus explicit
# discriminating cases for each plausible bug (divisor assignment, integer
# truncation, the 183 `>=` boundary, and the 31-day gate).

def _spt_oracle(cur: int, p1: int, p2: int) -> bool:
    # IRS Substantial Presence Test, stated independently: >=31 days current AND
    # weighted (current + prior_1/3 + prior_2/6) >= 183, using EXACT fractions.
    if cur < 31:
        return False
    return cur + p1 / 3.0 + p2 / 6.0 >= 183.0


def test_spt_matches_oracle_across_asymmetric_grid():
    currents = [0, 15, 30, 31, 60, 90, 120, 150, 180, 183, 200, 300, 366]
    priors = [0, 30, 45, 60, 120, 180, 240, 300, 366]
    checked = 0
    for cur in currents:
        for p1 in priors:
            for p2 in priors:
                got = us_substantial_presence(cur, p1, p2)
                want = _spt_oracle(cur, p1, p2)
                assert got is want, (
                    f"SPT diverged from IRS oracle at "
                    f"(current={cur}, prior_1={p1}, prior_2={p2}): got {got}, want {want}"
                )
                checked += 1
    assert checked == len(currents) * len(priors) * len(priors)


def test_spt_divisor_assignment_prior1_is_one_third():
    # Discriminator the equal-prior examples miss: prior_1 weighted by 1/3
    # (not 1/6). 170 + 39/3 + 0 = 170 + 13 = 183 -> True. If prior_1 wrongly used
    # 1/6 (a /3<->/6 swap), it would be 170 + 6.5 = 176.5 -> False.
    assert us_substantial_presence(170, 39, 0) is True


def test_spt_uses_exact_fractions_not_integer_truncation():
    # 180 + 8/3 + 2/6 = 180 + 2.6667 + 0.3333 = 183.0 EXACTLY -> True.
    # Integer-truncating each term (180 + 2 + 0 = 182) would wrongly give False.
    assert us_substantial_presence(180, 8, 2) is True
    # And just below the line stays False: 180 + 8/3 + 1/6 = 182.833 -> False.
    assert us_substantial_presence(180, 8, 1) is False


def test_spt_183_threshold_is_inclusive():
    # weighted == 183 exactly -> resident (`>=`, not `>`).
    assert us_substantial_presence(123, 120, 120) is True   # 123 + 40 + 20 = 183
    assert us_substantial_presence(122, 120, 120) is False  # 122 + 40 + 20 = 182


def test_spt_31_day_gate_overrides_weighted_sum():
    # The 31-day current-year gate is independent of the weighted sum: 30 days
    # current fails even when history alone would clear 183; 31 days can pass.
    assert us_substantial_presence(30, 459, 0) is False  # 30 + 153 = 183 but gate fails
    assert us_substantial_presence(31, 456, 0) is True   # 31 + 152 = 183, gate ok


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
