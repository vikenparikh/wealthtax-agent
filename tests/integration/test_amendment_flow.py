"""Amendment artifact is emitted when ``state.is_amendment`` is True."""

import base64
from unittest.mock import patch

from wealthtax_agent.build_return import build_return_node
from wealthtax_agent.engines.ca_engine import compute_ca_return
from wealthtax_agent.engines.us_engine import compute_us_return
from wealthtax_agent.optimize import optimize_node
from wealthtax_agent.state import FormExtract, GraphState


def test_ca_amendment_artifact_shows_three_column_diff():
    extracts = [FormExtract(form_code="T4", jurisdiction="CA",
                            fields={"employment_income": 90000.0, "income_tax_deducted": 16000.0})]
    draft = compute_ca_return(extracts, year=2024, province="ON")
    state = GraphState(
        filing_year=2024,
        jurisdictions=["CA"],
        user_answers={"province_of_residence": "ON"},
        extracts=extracts,
        draft_returns={"CA": draft},
        is_amendment=True,
        prior_filed_totals={"CA": {"total_income": 85000.0, "taxable_income": 85000.0,
                                    "total_tax": 18000.0, "refund": 0.0, "balance_owing": 2000.0}},
    )
    with patch("wealthtax_agent.optimize._llm_rerank", side_effect=lambda x: x):
        state = optimize_node(state)
    state = build_return_node(state)

    assert "ca_amendment" in state.filing_artifacts
    text = base64.b64decode(state.filing_artifacts["ca_amendment"].content_b64).decode("utf-8")
    assert "T1-ADJ" in text
    assert "85,000.00" in text
    assert "Difference" in text


def test_us_amendment_emits_1040x_worksheet():
    extracts = [FormExtract(form_code="W-2", jurisdiction="US",
                            fields={"wages": 95000.0, "federal_income_tax_withheld": 12000.0})]
    draft = compute_us_return(extracts, year=2024, user_answers={"filing_status": "single"})
    state = GraphState(
        filing_year=2024,
        jurisdictions=["US"],
        user_answers={"filing_status": "single"},
        extracts=extracts,
        draft_returns={"US": draft},
        is_amendment=True,
        prior_filed_totals={"US": {"total_income": 90000.0, "taxable_income": 75400.0,
                                    "total_tax": 12000.0, "refund": 0.0, "balance_owing": 0.0}},
    )
    with patch("wealthtax_agent.optimize._llm_rerank", side_effect=lambda x: x):
        state = optimize_node(state)
    state = build_return_node(state)

    assert "us_amendment" in state.filing_artifacts
    text = base64.b64decode(state.filing_artifacts["us_amendment"].content_b64).decode("utf-8")
    assert "1040-X" in text
    assert "90,000.00" in text


def test_no_amendment_artifact_when_flag_false():
    extracts = [FormExtract(form_code="T4", jurisdiction="CA", fields={"employment_income": 70000.0})]
    draft = compute_ca_return(extracts, year=2024, province="ON")
    state = GraphState(
        filing_year=2024,
        jurisdictions=["CA"],
        user_answers={"province_of_residence": "ON"},
        extracts=extracts,
        draft_returns={"CA": draft},
        is_amendment=False,
    )
    state = build_return_node(state)
    assert "ca_amendment" not in state.filing_artifacts
