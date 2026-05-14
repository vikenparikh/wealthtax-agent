"""First pass through the graph pauses for clarifying answers; a second pass
with answers populated continues to ``reason_tax`` and produces a draft."""

from unittest.mock import patch

from wealthtax_agent.clarify import ask_clarifications_node
from wealthtax_agent.optimize import optimize_node
from wealthtax_agent.reason_tax import reason_tax_node
from wealthtax_agent.state import FormExtract, GraphState


def test_pause_then_resume_with_answers():
    state = GraphState(
        filing_year=2024,
        jurisdictions=["CA"],
        extracts=[FormExtract(form_code="T4", jurisdiction="CA", fields={"employment_income": 60000.0})],
    )

    # First pass: no answers -> pause expected
    state = ask_clarifications_node(state)
    assert state.awaiting_clarification is True

    # Provide high-priority answers and recompute
    state.user_answers = {
        "marital_status": "single",
        "province_of_residence": "ON",
        "foreign_property_over_100k": "no",
    }
    state = ask_clarifications_node(state)
    assert state.awaiting_clarification is False

    state = reason_tax_node(state)
    with patch("wealthtax_agent.optimize._llm_rerank", side_effect=lambda x: x):
        state = optimize_node(state)

    assert "CA" in state.draft_returns
    assert state.draft_returns["CA"].estimated_tax > 0
