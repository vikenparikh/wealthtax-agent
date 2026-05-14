"""Engines must produce numerically correct drafts even when the LLM is broken.

We monkeypatch every LLM entry point to raise, then run the deterministic part
of the pipeline (reason_tax -> optimize -> build_return) and assert the draft
return still computes and the filing artifacts are generated.
"""

from unittest.mock import patch

from wealthtax_agent.build_return import build_return_node
from wealthtax_agent.optimize import optimize_node
from wealthtax_agent.reason_tax import reason_tax_node
from wealthtax_agent.state import FormExtract, GraphState


def _raise(*args, **kwargs):
    raise RuntimeError("LLM unavailable")


def test_pipeline_succeeds_when_llm_unavailable():
    with patch("wealthtax_agent.optimize.call_with_retry", side_effect=_raise), \
         patch("wealthtax_agent.optimize.get_client", side_effect=_raise):

        state = GraphState(
            filing_year=2024,
            jurisdictions=["CA"],
            user_answers={"province_of_residence": "ON"},
            extracts=[FormExtract(form_code="T4", jurisdiction="CA", fields={"employment_income": 70000.0})],
        )

        state = reason_tax_node(state)
        state = optimize_node(state)
        state = build_return_node(state)

    assert state.draft_returns["CA"].total_income == 70000.0
    assert state.draft_returns["CA"].estimated_tax > 0
    assert "ca_t1_pdf" in state.filing_artifacts
