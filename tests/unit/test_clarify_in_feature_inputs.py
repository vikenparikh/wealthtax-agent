"""IN filers must be asked for the Chapter VI-A deduction inputs the engine reads.

Each deduction is computed by the in_engine but gated on a user_answers key that
no clarifying question surfaced, so an IN filer was never prompted and the
deduction stayed dormant (old regime):
  - section_80ccd_1b_nps        -> extra Rs 50,000 NPS deduction
  - section_80d_parents_premium -> §80D parents' health insurance
  - section_80ddb_medical       -> §80DDB specified-disease treatment (#132)
  - section_80eeb_ev_loan_interest -> §80EEB EV-loan interest (#133)
  - section_80g_donations       -> §80G charitable donations
  - section_80ggc_political_donation -> §80GGC political donations (#146)
  - taxpayer_disability         -> §80U self disability (#130)
  - dependent_disability        -> §80DD dependant disability (#130)
"""
import pytest
from wealthtax_agent.clarify import ask_clarifications_node
from wealthtax_agent.state import GraphState


def _in_pending_ids(answers=None):
    state = GraphState(jurisdictions=["IN"], user_answers=answers or {})
    return {q.id for q in ask_clarifications_node(state).clarifying_questions}


@pytest.mark.parametrize("qid", [
    "section_80ccd_1b_nps",
    "section_80d_parents_premium",
    "section_80ddb_medical",
    "section_80eeb_ev_loan_interest",
    "section_80g_donations",
    "section_80ggc_political_donation",
    "taxpayer_disability",
    "dependent_disability",
])
def test_in_filer_is_asked_for_deduction_input(qid):
    assert qid in _in_pending_ids()


def test_answered_in_deduction_input_not_re_asked():
    assert "section_80ggc_political_donation" not in _in_pending_ids(
        {"section_80ggc_political_donation": "50000"})
