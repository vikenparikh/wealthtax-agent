"""Branch coverage for optimize.py suggestion rules and clarify.py pausing.

test_optimize.py asserts only RRSP/401k titles + sort order; test_clarify.py
covers CA only. These pin the per-rule CA/US suggestion branches (called
directly — they make no LLM call), the IN no-op in optimize_node, and the
clarify IN pause plus the documented "any answers suppress the pause" quirk.
Suggestion ids/branches verified against the implementation; the exit-gated
run confirms every value.
"""

from unittest.mock import patch

from wealthtax_agent.clarify import ask_clarifications_node
from wealthtax_agent.optimize import _suggest_ca, _suggest_us, optimize_node
from wealthtax_agent.state import DraftReturn, FormExtract, GraphState


def _ids(suggestions):
    return {s.id for s in suggestions}


def _by_id(suggestions, sid):
    return next(s for s in suggestions if s.id == sid)


def _ca_draft():
    return DraftReturn(
        jurisdiction="CA", tax_year=2024, taxable_income=78000.0,
        line_items={"employment_income": 80000.0}, totals={"taxable_income": 78000.0},
    )


# --- optimize: CA rules ------------------------------------------------------


def test_ca_capital_loss_harvest_branch():
    extracts = [FormExtract(form_code="T5008", jurisdiction="CA", fields={"capital_gain": -4000.0})]
    out = _suggest_ca(extracts, _ca_draft(), 2024, {"rrsp_room_remaining": "0", "home_buyer_first": "yes"})
    assert "capital_loss_harvest_ca" in _ids(out)
    assert "4,000" in _by_id(out, "capital_loss_harvest_ca").title


def test_ca_tuition_transfer_capped_at_5000():
    extracts = [FormExtract(form_code="T2202", jurisdiction="CA", fields={"eligible_tuition_fees": 8000.0})]
    out = _suggest_ca(extracts, _ca_draft(), 2024, {"rrsp_room_remaining": "0", "home_buyer_first": "yes"})
    assert "tuition_transfer" in _ids(out)
    assert "5,000" in _by_id(out, "tuition_transfer").title  # min(8000, 5000)


def test_ca_fhsa_suppressed_when_already_a_homeowner_intent():
    answers = {"rrsp_room_remaining": "0", "home_buyer_first": "yes"}
    assert "fhsa" not in _ids(_suggest_ca([], _ca_draft(), 2024, answers))
    # default (no home_buyer_first flag) surfaces FHSA
    assert "fhsa" in _ids(_suggest_ca([], _ca_draft(), 2024, {"rrsp_room_remaining": "0"}))


def test_ca_rrsp_room_non_numeric_falls_back_to_income_estimate():
    out = _suggest_ca([], _ca_draft(), 2024, {"rrsp_room_remaining": "notanumber"})
    assert "rrsp_topup" in _ids(out)  # ValueError fallback re-estimates room from income


# --- optimize: US rules ------------------------------------------------------


def test_us_emits_ira_hsa_caploss_studentloan_rules():
    draft = DraftReturn(
        jurisdiction="US",
        line_items={"wages": 80000, "short_term_capital_gain": 2000,
                    "long_term_capital_gain": 5000, "student_loan_interest_deduction": 1800},
        totals={"agi": 80000},
    )
    ids = _ids(_suggest_us([], draft, 2024, {"filing_status": "single", "hsa_eligible": "yes"}))
    assert {"ira_or_roth", "hsa_max", "capital_loss_harvest_us", "student_loan_interest_claimed"} <= ids


def test_us_ira_suppressed_above_150k_agi():
    draft = DraftReturn(jurisdiction="US", line_items={"wages": 200000}, totals={"agi": 200000})
    assert "ira_or_roth" not in _ids(_suggest_us([], draft, 2024, {"filing_status": "single"}))


# --- optimize_node dispatch --------------------------------------------------


def test_optimize_node_is_noop_for_india():
    draft = DraftReturn(jurisdiction="IN", taxable_income=900000.0, totals={"taxable_income": 900000.0})
    state = GraphState(filing_year=2024, jurisdictions=["IN"], draft_returns={"IN": draft})
    with patch("wealthtax_agent.optimize._llm_rerank", side_effect=lambda x: x):
        out = optimize_node(state)
    assert out.optimization_suggestions == []


# --- clarify -----------------------------------------------------------------


def test_clarify_pauses_on_india_high_priority_questions():
    out = ask_clarifications_node(GraphState(jurisdictions=["IN"], user_answers={}))
    assert out.awaiting_clarification is True
    high_ids = {q.id for q in out.clarifying_questions if getattr(q, "priority", None) == "high"}
    assert {"in_regime", "age", "is_indian_citizen"} <= high_ids


def test_clarify_any_answers_suppress_the_pause_quirk():
    # Documented quirk: awaiting = high_priority_pending AND not bool(answers),
    # so ANY non-empty answers dict suppresses the pause even with high-priority gaps.
    out = ask_clarifications_node(GraphState(jurisdictions=["CA"], user_answers={"marital_status": "single"}))
    assert out.awaiting_clarification is False
    assert out.clarifying_questions  # high-priority questions still remain
