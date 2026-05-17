"""YoY planning artifact embeds a 5-year projection table."""

import base64
from unittest.mock import patch

from wealthtax_agent.build_return import build_return_node
from wealthtax_agent.engines.ca_engine import compute_ca_return
from wealthtax_agent.optimize import optimize_node
from wealthtax_agent.state import FormExtract, GraphState


def test_planning_artifact_includes_projection_table():
    extracts = [FormExtract(form_code="T4", jurisdiction="CA", fields={"employment_income": 80000.0})]
    state = GraphState(
        filing_year=2024,
        jurisdictions=["CA"],
        user_answers={"province_of_residence": "ON"},
        extracts=extracts,
        draft_returns={"CA": compute_ca_return(extracts, year=2024, province="ON")},
    )
    with patch("wealthtax_agent.optimize._llm_rerank", side_effect=lambda x: x):
        state = optimize_node(state)
    state = build_return_node(state)

    text = base64.b64decode(state.filing_artifacts["yoy_planning"].content_b64).decode("utf-8")
    assert "5-Year Projection" in text
    # The first projected year is filing_year + 1 = 2025
    assert "2025" in text
    assert "2029" in text  # five years out
