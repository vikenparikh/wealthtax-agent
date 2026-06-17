"""US filers must be asked for the inputs that gate the §21 dependent-care credit.

The engine computes the Form 2441 Child & Dependent Care Credit (us_engine.py
_compute_dependent_care_credit), but it requires BOTH user_answers keys:
  - dependent_care_expenses        -> qualifying care expenses paid
  - num_dependent_care_persons     -> number of qualifying persons
Without clarifying questions surfacing both, the filer is never prompted and the
credit stays dormant (returns 0 unless BOTH keys are present and positive).
"""
import pytest
from wealthtax_agent.clarify import ask_clarifications_node
from wealthtax_agent.engines.us_engine import compute_us_return
from wealthtax_agent.state import GraphState, FormExtract


def _us_pending_ids(answers=None):
    state = GraphState(jurisdictions=["US"], user_answers=answers or {})
    return {q.id for q in ask_clarifications_node(state).clarifying_questions}


@pytest.mark.parametrize("qid", [
    "dependent_care_expenses",
    "num_dependent_care_persons",
])
def test_us_filer_is_asked_for_dependent_care_input(qid):
    assert qid in _us_pending_ids()


def test_answered_dependent_care_inputs_not_re_asked():
    answered = {"dependent_care_expenses": "6000", "num_dependent_care_persons": "2"}
    pending = _us_pending_ids(answered)
    assert "dependent_care_expenses" not in pending
    assert "num_dependent_care_persons" not in pending


def _w2_60k():
    return [FormExtract(
        form_code="W-2",
        jurisdiction="US",
        fields={"wages": 60000.0, "federal_income_tax_withheld": 0.0},
    )]


def test_dependent_care_credit_reachable_via_both_keys():
    """Reachability guard: BOTH keys -> $1,200 lower; expenses-only -> $0 delta."""
    baseline = compute_us_return(_w2_60k(), 2024, user_answers={})
    base_tax = baseline.totals["total_tax"]

    both = compute_us_return(
        _w2_60k(), 2024,
        user_answers={"dependent_care_expenses": "6000",
                      "num_dependent_care_persons": "2"},
    )
    assert base_tax - both.totals["total_tax"] == pytest.approx(1200.0)

    expenses_only = compute_us_return(
        _w2_60k(), 2024,
        user_answers={"dependent_care_expenses": "6000"},
    )
    assert expenses_only.totals["total_tax"] == pytest.approx(base_tax)
