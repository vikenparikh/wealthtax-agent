"""CA filers must be asked for the inputs that gate recently-shipped CA features.

Each of these features is computed by the engine but gated on a user_answers
key. Without a clarifying question, a CA filer is never prompted and the feature
stays dormant:
  - home_buyers_amount            -> Home Buyers' Amount credit (line 31270)
  - mhrtc_qualifying_expenditure  -> Multigenerational Home Renovation credit
  - security_option_benefit       -> Security options deduction (line 24900)
  - volunteer_firefighter_amount  -> Volunteer Firefighters' Amount (line 31220)
  - search_rescue_volunteer_amount-> Search & Rescue Volunteers' Amount (31240)
"""
import pytest
from wealthtax_agent.clarify import ask_clarifications_node
from wealthtax_agent.state import GraphState


def _ca_pending_ids(answers=None):
    state = GraphState(jurisdictions=["CA"], user_answers=answers or {})
    return {q.id for q in ask_clarifications_node(state).clarifying_questions}


@pytest.mark.parametrize("qid", [
    "home_buyers_amount",
    "mhrtc_qualifying_expenditure",
    "security_option_benefit",
    "volunteer_firefighter_amount",
    "search_rescue_volunteer_amount",
])
def test_ca_filer_is_asked_for_feature_input(qid):
    assert qid in _ca_pending_ids()


def test_answered_feature_input_not_re_asked():
    assert "home_buyers_amount" not in _ca_pending_ids({"home_buyers_amount": "10000"})
