"""Edge-case branches of the cross-border guardrails.

``test_cross_border.py`` covers the happy paths (US-wins, IN-wins, single
claim, basic RSU/FTC). These tests pin the branches it does not reach:

* ``_highest_marginal_jurisdiction`` falling back to preference order when
  no draft has a computable marginal rate,
* a three-jurisdiction simultaneous student-loan claim (CA-zeroing branch),
* empty ``draft_returns`` short-circuits,
* the FTC zero-source-tax guard and residency-status aliases (RNOR /
  dual_status),
* ``cross_border_node`` aggregating loan warnings + FTC notes and
  de-duplicating on a second pass,
* RSU sourcing negative-value guard and cent rounding.

All money-handling guardrail logic — a wrong "keep" decision means a
deduction lands in the wrong jurisdiction's draft.
"""

from wealthtax_agent.engines.cross_border import (
    cross_border_node,
    enforce_single_student_loan,
    foreign_tax_credit_hint,
    rsu_sourcing_split,
)
from wealthtax_agent.state import DraftReturn, GraphState


def _loan_draft(jurisdiction, key, amount, taxable, total_tax):
    return DraftReturn(
        jurisdiction=jurisdiction,
        line_items={key: amount},
        totals={"taxable_income": taxable, "total_tax": total_tax},
    )


# --- enforce_single_student_loan -------------------------------------------------


def test_enforce_no_drafts_returns_empty():
    assert enforce_single_student_loan(GraphState()) == []


def test_three_jurisdiction_claim_keeps_highest_marginal_zeros_other_two():
    state = GraphState(
        draft_returns={
            "US": _loan_draft("US", "student_loan_interest_deduction", 2500.0, 100000.0, 35000.0),  # 0.35
            "CA": _loan_draft("CA", "student_loan_interest_ca", 3000.0, 100000.0, 25000.0),         # 0.25
            "IN": _loan_draft("IN", "section_80e", 40000.0, 100000.0, 20000.0),                     # 0.20
        },
    )
    warnings = enforce_single_student_loan(state)
    assert state.draft_returns["US"].line_items["student_loan_interest_deduction"] == 2500.0
    assert state.draft_returns["CA"].line_items["student_loan_interest_ca"] == 0.0
    assert state.draft_returns["IN"].line_items["section_80e"] == 0.0
    assert len(warnings) == 2
    assert any("Removed from CA" in w for w in warnings)
    assert any("Removed from IN" in w for w in warnings)


def test_fallback_to_preference_order_when_no_taxable_income():
    # No draft has positive taxable income, so no marginal rate can be
    # computed; the helper falls back to preference order ['US','CA','IN'].
    state = GraphState(
        draft_returns={
            "CA": _loan_draft("CA", "student_loan_interest_ca", 3000.0, 0.0, 0.0),
            "US": _loan_draft("US", "student_loan_interest_deduction", 2500.0, 0.0, 0.0),
        },
    )
    warnings = enforce_single_student_loan(state)
    # US precedes CA in preference order → US kept, CA removed.
    assert state.draft_returns["US"].line_items["student_loan_interest_deduction"] == 2500.0
    assert state.draft_returns["CA"].line_items["student_loan_interest_ca"] == 0.0
    assert any("Removed from CA" in w for w in warnings)


def test_warning_message_includes_amount_and_keep_jurisdiction():
    state = GraphState(
        draft_returns={
            "US": _loan_draft("US", "student_loan_interest_deduction", 2500.0, 100000.0, 30000.0),  # 0.30
            "IN": _loan_draft("IN", "section_80e", 40000.0, 100000.0, 10000.0),                     # 0.10
        },
    )
    warnings = enforce_single_student_loan(state)
    assert len(warnings) == 1
    w = warnings[0]
    assert "$40,000.00" in w          # the zeroed IN amount, formatted
    assert "both IN and US" in w
    assert "lower marginal" in w


# --- foreign_tax_credit_hint -----------------------------------------------------


def test_no_ftc_hint_when_source_tax_is_zero():
    state = GraphState(
        residency_status={"US": "nonresident", "CA": "resident"},
        draft_returns={
            "US": DraftReturn(jurisdiction="US", totals={"taxable_income": 80000.0, "total_tax": 0.0}),
            "CA": DraftReturn(jurisdiction="CA", totals={"taxable_income": 80000.0, "total_tax": 18000.0}),
        },
    )
    assert foreign_tax_credit_hint(state) == []


def test_ftc_hint_honors_rnor_and_dual_status_aliases():
    state = GraphState(
        residency_status={"IN": "RNOR", "US": "dual_status"},
        draft_returns={
            "IN": DraftReturn(jurisdiction="IN", totals={"taxable_income": 500000.0, "total_tax": 50000.0}),
            "US": DraftReturn(jurisdiction="US", totals={"taxable_income": 80000.0, "total_tax": 12000.0}),
        },
    )
    notes = foreign_tax_credit_hint(state)
    # RNOR is resident-like, dual_status is nonresident-like → IN credits US tax.
    assert any("IN resident may credit up to $12,000.00 of US tax" in n for n in notes)
    # Only one direction credits (US dual_status is not resident-like).
    assert len(notes) == 1


# --- cross_border_node -----------------------------------------------------------


def _node_state():
    return GraphState(
        residency_status={"US": "nonresident", "CA": "resident"},
        draft_returns={
            "US": _loan_draft("US", "student_loan_interest_deduction", 2500.0, 100000.0, 30000.0),  # 0.30
            "CA": _loan_draft("CA", "student_loan_interest_ca", 3000.0, 100000.0, 20000.0),         # 0.20
        },
    )


def test_cross_border_node_appends_loan_warning_and_ftc_note():
    state = _node_state()
    result = cross_border_node(state)
    assert result is state
    # US has the higher marginal rate → CA's claim is zeroed.
    assert state.draft_returns["CA"].line_items["student_loan_interest_ca"] == 0.0
    assert any("student-loan interest" in w for w in state.warnings)
    # CA resident crediting US (nonresident) source tax → FTC hint present.
    assert any("CA resident may credit up to" in w for w in state.warnings)


def test_cross_border_node_does_not_duplicate_warnings_on_second_pass():
    state = _node_state()
    cross_border_node(state)
    first = list(state.warnings)
    cross_border_node(state)  # idempotent: dedup guard blocks re-append
    assert state.warnings == first


def test_cross_border_node_is_noop_without_drafts():
    state = GraphState()
    result = cross_border_node(state)
    assert result is state
    assert state.warnings == []


# --- rsu_sourcing_split ----------------------------------------------------------


def test_rsu_sourcing_zero_when_value_negative():
    assert rsu_sourcing_split(-100.0, 50, 50) == {"US": 0.0, "CA": 0.0, "IN": 0.0}


def test_rsu_sourcing_rounds_to_cents():
    split = rsu_sourcing_split(10000.0, 1, 1, 1)
    assert split["US"] == 3333.33
    assert split["CA"] == 3333.33
    assert split["IN"] == 3333.33
