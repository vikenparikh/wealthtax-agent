"""US filers must be asked for the inputs that gate recently-shipped US features.

Each feature is computed by the engine but gated on a user_answers key; without
a clarifying question the filer is never prompted and the feature stays dormant:
  - residential_clean_energy_cost  -> §25D clean-energy credit (#144)
  - energy_efficient_improvements  -> §25C efficiency credit (#144)
  - heat_pump_cost                 -> §25C heat-pump cap (#144)
  - used_clean_vehicle_price       -> §25E used clean vehicle credit (#149)
  - foreign_source_income          -> Foreign Tax Credit / §904 (#153)
  - foreign_tax_paid               -> Foreign Tax Credit (#153)
  - principal_residence_gain       -> §121 home-sale exclusion (#155)
"""
import pytest
from wealthtax_agent.clarify import ask_clarifications_node
from wealthtax_agent.state import GraphState


def _us_pending_ids(answers=None):
    state = GraphState(jurisdictions=["US"], user_answers=answers or {})
    return {q.id for q in ask_clarifications_node(state).clarifying_questions}


@pytest.mark.parametrize("qid", [
    "residential_clean_energy_cost",
    "energy_efficient_improvements",
    "heat_pump_cost",
    "used_clean_vehicle_price",
    "foreign_source_income",
    "foreign_tax_paid",
    "principal_residence_gain",
])
def test_us_filer_is_asked_for_feature_input(qid):
    assert qid in _us_pending_ids()


def test_answered_us_feature_input_not_re_asked():
    assert "foreign_tax_paid" not in _us_pending_ids({"foreign_tax_paid": "9000"})
