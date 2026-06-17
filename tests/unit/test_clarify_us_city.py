"""US filers must be asked for their city of residence.

The engine computes NYC resident income tax and the Yonkers surcharge, but both
are gated on user_answers["city_of_residence"]. Without a clarifying question
for it, a US filer is never prompted, so those local taxes stay dormant — the
shipped feature is unreachable through the normal intake flow.
"""
from wealthtax_agent.clarify import ask_clarifications_node
from wealthtax_agent.state import GraphState


def _pending_ids(jurisdictions, answers):
    state = GraphState(jurisdictions=jurisdictions, user_answers=answers)
    out = ask_clarifications_node(state)
    return {q.id for q in out.clarifying_questions}


def test_us_filer_is_asked_for_city_of_residence():
    ids = _pending_ids(["US"], {})
    assert "city_of_residence" in ids


def test_city_question_not_pending_once_answered():
    ids = _pending_ids(["US"], {"city_of_residence": "Brooklyn"})
    assert "city_of_residence" not in ids


def test_city_question_still_present_for_india_filers():
    # Regression: IN already had this question; it must remain.
    ids = _pending_ids(["IN"], {})
    assert "city_of_residence" in ids
