"""Unit tests for ``residency_test_node`` — the graph node in engines/residency.py.

Covers the ACTIVE path (state.residency_days set): building the ``prior`` dict by
parsing ``prior_year_days_{us,ca,in}_*`` keys out of ``user_answers`` (int-coerce,
comma-strip, skip on ValueError), calling ``recommend_residency``, writing
``residency_status``/``residency_notes``, and appending de-duped notes into
``state.warnings``.

Also exercises the ``ValueError`` fallback (``ror_years = 2``) in
``recommend_residency`` when ``india_resident_years_in_last_10`` is non-numeric.

Pure functions, no LLM / DB / network — zero mocks.
"""

from wealthtax_agent.engines.residency import (
    _TREATY_HINTS,
    ca_residency,
    india_residency,
    recommend_residency,
    residency_test_node,
    us_residency,
)
from wealthtax_agent.state import GraphState


def _tri_country_state() -> GraphState:
    """US + CA + IN all resident-like, to trigger all three treaty-hint notes."""
    return GraphState(
        jurisdictions=["US", "CA", "IN"],
        residency_days={"US": 250, "CA": 200, "IN": 300},
        user_answers={
            # US prior-year keys: one plain, one comma-formatted, one non-numeric (skip).
            "prior_year_days_us_prior_1": "120",
            "prior_year_days_us_prior_2": "1,000",   # comma-strip branch
            "prior_year_days_us_bogus": "not-a-number",  # ValueError → skip branch
            # CA has no prior keys → per_country empty → not added to prior.
            # IN prior keys drive the ROR/RNOR path.
            "prior_year_days_in_prior_7_days": "800",
            "prior_year_days_in_prior_4_total": "400",
            # Non-numeric → hits recommend_residency lines 203-204 (ror_years = 2).
            "india_resident_years_in_last_10": "several",
        },
        filing_year=2024,
    )


def test_no_op_when_no_residency_days():
    """Guard clause: empty residency_days returns state untouched."""
    state = GraphState(jurisdictions=["US"], filing_year=2024)
    out = residency_test_node(state)
    assert out is state
    assert out.residency_status == {}
    assert out.residency_notes == []


def test_active_path_sets_status_for_all_three_countries():
    state = _tri_country_state()
    out = residency_test_node(state)

    assert out.residency_status["US"] == "resident"       # SPT passes at 250 days
    assert out.residency_status["CA"] == "resident"       # 200 >= 183
    assert out.residency_status["IN"] in {"ROR", "RNOR"}  # 300 >= 182 → resident-like


def test_active_path_emits_all_three_treaty_hints_as_notes():
    state = _tri_country_state()
    out = residency_test_node(state)

    for pair in (("US", "CA"), ("US", "IN"), ("CA", "IN")):
        hint = _TREATY_HINTS[pair]
        assert hint in out.residency_notes
        assert hint in out.warnings


def test_notes_are_mirrored_into_warnings_without_duplicates():
    state = _tri_country_state()
    # Pre-seed warnings with one treaty hint so the de-dup branch (note in warnings)
    # is exercised: it must NOT be appended a second time.
    preseeded = _TREATY_HINTS[("US", "CA")]
    state.warnings.append(preseeded)

    out = residency_test_node(state)

    # Every note appears in warnings exactly once.
    for note in out.residency_notes:
        assert out.warnings.count(note) == 1


def test_comma_and_nonnumeric_prior_keys_are_parsed_and_skipped():
    """The comma-formatted US prior key is coerced; the non-numeric one is skipped.

    We verify indirectly: the parsed prior dict feeds recommend_residency, and the
    node must complete without raising despite the bogus key.
    """
    state = _tri_country_state()
    out = residency_test_node(state)

    # Node completed and produced a full status set → the skip branch did not raise.
    assert set(out.residency_status) == {"US", "CA", "IN"}
    # Notes list is non-empty (treaty hints present).
    assert out.residency_notes


def test_node_emits_near_threshold_notes_for_us_and_india():
    """Node path hits the 'close to threshold' note branches in recommend_residency.

    US weighted days in [170, 190) → SPT-proximity note (line 186).
    India days in [175, 189] → Section-6-proximity note (line 214).
    """
    state = GraphState(
        jurisdictions=["US", "IN"],
        residency_days={"US": 180, "IN": 180},
        user_answers={},
        filing_year=2024,
    )
    out = residency_test_node(state)

    assert any("Substantial Presence weighted days" in n for n in out.residency_notes)
    assert any("close to a Section 6 threshold" in n for n in out.residency_notes)


def test_pure_helper_branches():
    """Cover the remaining conditional branches in the pure residency helpers."""
    # us_residency: citizen/green-card short-circuit, and dual_status on move.
    assert us_residency(0, is_us_citizen=True) == "resident"
    assert us_residency(0, is_green_card=True) == "resident"
    assert us_residency(200, moved_in_or_out=True) == "dual_status"

    # us_residency: fewer than 31 days can never pass the substantial-presence test.
    assert us_residency(10, days_prior_1=1000) == "nonresident"

    # ca_residency: no ties + under 183 days → non_resident; primary-ties variants.
    assert ca_residency(50) == "non_resident"
    assert ca_residency(0, has_primary_ties=True) == "resident"
    assert ca_residency(0, has_primary_ties=True, moved_in_or_out=True) == "part_year_resident"

    # india_residency: NRI relaxed 182-day threshold, and §6(1A) deemed-RNOR path.
    assert india_residency(100, is_indian_citizen=True, indian_income_above_15l=False) == "NR"
    assert (
        india_residency(
            50, is_indian_citizen=True, indian_income_above_15l=True
        )
        == "RNOR"
    )


def test_recommend_residency_valueerror_fallback_for_ror_years():
    """Directly exercise lines 203-204: non-numeric india_resident_years_in_last_10.

    With prior_7 days >= 730 and a defaulted ror_years of 2, IN classifies as ROR.
    """
    result = recommend_residency(
        {"IN": 300},
        prior_year_days={"IN": {"prior_4_total": 400, "prior_7_days": 800}},
        user_answers={"india_resident_years_in_last_10": "several"},
    )
    assert result["status"]["IN"] == "ROR"
