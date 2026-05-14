"""End-to-end pipeline test for a CA filer with T4 + T5 + RRSP.

We bypass real OCR by injecting pre-built ``classifications`` and ``extracts``
into the graph state and running from ``reason_tax`` onward (the LangGraph
graph is linear after extraction). This avoids needing PDF rendering libraries
in CI for the integration suite.
"""

from unittest.mock import patch

from wealthtax_agent.build_return import build_return_node
from wealthtax_agent.optimize import optimize_node
from wealthtax_agent.reason_tax import reason_tax_node
from wealthtax_agent.state import FormExtract, GraphState


def test_ca_full_pipeline_produces_artifacts():
    state = GraphState(
        filing_year=2024,
        jurisdictions=["CA"],
        user_answers={"province_of_residence": "ON", "marital_status": "single", "foreign_property_over_100k": "no"},
        extracts=[
            FormExtract(form_code="T4", jurisdiction="CA", fields={"employment_income": 80000.0, "income_tax_deducted": 14500.0}),
            FormExtract(form_code="T5", jurisdiction="CA", fields={"interest_income": 1200.0, "taxable_eligible_dividends": 1380.0}),
            FormExtract(form_code="RRSP", jurisdiction="CA", fields={"rrsp_contributions": 7000.0}),
        ],
    )

    state = reason_tax_node(state)
    with patch("wealthtax_agent.optimize._llm_rerank", side_effect=lambda x: x):
        state = optimize_node(state)
    state = build_return_node(state)

    assert "CA" in state.draft_returns
    ca = state.draft_returns["CA"]
    assert ca.total_income == 80000.0 + 1200.0 + 1380.0
    assert ca.rrsp_deduction == 7000.0
    assert ca.estimated_tax > 0
    assert "ca_t1_pdf" in state.filing_artifacts
    assert "ca_netfile_xml" in state.filing_artifacts
    assert state.optimization_suggestions  # at least one suggestion
