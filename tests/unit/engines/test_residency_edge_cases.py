"""Boundary + branch coverage for residency rules (engines/residency.py).

test_residency.py covers the common cases; these pin the exact statutory
boundaries and the distinct code paths that produce the same status, plus
the recommend_residency proximity note, the CA-IN treaty hint, and the
unknown-jurisdiction no-op. All expected values were confirmed by running
the implementation read-only.
"""

from wealthtax_agent.engines.residency import (
    ca_residency,
    india_residency,
    recommend_residency,
)


def test_india_60_day_plus_365_prior_boundary():
    # 60 days current + 365 in the prior 4 years => resident (RNOR); 59 => NR.
    assert india_residency(60, 365) == "RNOR"
    assert india_residency(59, 365) == "NR"


def test_india_ror_vs_rnor_at_730_prior_resident_days():
    assert india_residency(200, 400, days_prior_7_resident_years=730) == "ROR"
    assert india_residency(200, 400, days_prior_7_resident_years=729) == "RNOR"


def test_india_citizen_high_income_resident_by_days_is_rnor():
    # Reaches RNOR via the normal resident path (>=182 days), not the
    # deemed-resident §6(1A) branch (which only applies when days < 182).
    assert india_residency(182, 0, is_indian_citizen=True, indian_income_above_15l=True) == "RNOR"


def test_ca_move_flag_ignored_without_primary_ties():
    # The move flag only triggers part-year status under primary ties; the
    # 183-day limb alone yields plain resident.
    assert ca_residency(200, moved_in_or_out=True) == "resident"


def test_recommend_flags_india_section6_proximity():
    r = recommend_residency({"IN": 60}, prior_year_days={"IN": {"prior_4_total": 365}})
    assert r["status"] == {"IN": "RNOR"}
    assert any("close to a Section 6 threshold" in n for n in r["notes"])


def test_recommend_emits_canada_india_treaty_hint():
    r = recommend_residency({"CA": 200, "IN": 200}, prior_year_days={"IN": {"prior_4_total": 400}})
    assert any("Canada-India" in n for n in r["notes"])


def test_recommend_is_noop_for_unknown_jurisdiction():
    assert recommend_residency({"UK": 300}) == {"status": {}, "notes": []}
