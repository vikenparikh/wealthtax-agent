from unittest.mock import patch

from wealthtax_agent.optimize import optimize_node
from wealthtax_agent.state import DraftReturn, FormExtract, GraphState


def _state_with_ca_draft(rrsp_room: str = "20000") -> GraphState:
    draft = DraftReturn(
        jurisdiction="CA",
        tax_year=2024,
        total_income=80000.0,
        rrsp_deduction=2000.0,
        taxable_income=78000.0,
        estimated_tax=15000.0,
        line_items={"employment_income": 80000.0},
        totals={"total_income": 80000.0, "taxable_income": 78000.0, "total_tax": 15000.0},
    )
    return GraphState(
        filing_year=2024,
        jurisdictions=["CA"],
        user_answers={"rrsp_room_remaining": rrsp_room},
        extracts=[FormExtract(form_code="T4", jurisdiction="CA", fields={"employment_income": 80000.0})],
        draft_returns={"CA": draft},
    )


def test_optimize_suggests_rrsp_topup_when_room_available():
    state = _state_with_ca_draft(rrsp_room="20000")
    with patch("wealthtax_agent.optimize._llm_rerank", side_effect=lambda x: x):
        result = optimize_node(state)
    titles = [s.title for s in result.optimization_suggestions]
    assert any("RRSP" in t for t in titles)


def test_optimize_suggests_us_401k_for_wage_earner():
    draft = DraftReturn(
        jurisdiction="US",
        tax_year=2024,
        total_income=80000.0,
        taxable_income=65400.0,
        estimated_tax=10000.0,
        line_items={"wages": 80000.0},
        totals={"agi": 80000.0, "taxable_income": 65400.0},
    )
    state = GraphState(
        filing_year=2024,
        jurisdictions=["US"],
        user_answers={"filing_status": "single"},
        extracts=[FormExtract(form_code="W-2", jurisdiction="US", fields={"wages": 80000.0})],
        draft_returns={"US": draft},
    )
    with patch("wealthtax_agent.optimize._llm_rerank", side_effect=lambda x: x):
        result = optimize_node(state)
    titles = [s.title for s in result.optimization_suggestions]
    assert any("401(k)" in t for t in titles)


def test_optimize_sorted_by_estimated_savings_desc():
    state = _state_with_ca_draft(rrsp_room="20000")
    with patch("wealthtax_agent.optimize._llm_rerank", side_effect=lambda x: x):
        result = optimize_node(state)
    savings = [s.est_savings for s in result.optimization_suggestions]
    assert savings == sorted(savings, reverse=True)
