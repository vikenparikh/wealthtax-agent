"""End-to-end pipeline test for a US filer with W-2 + 1099-INT."""

import base64
import json
from unittest.mock import patch

from wealthtax_agent.build_return import build_return_node
from wealthtax_agent.optimize import optimize_node
from wealthtax_agent.reason_tax import reason_tax_node
from wealthtax_agent.state import FormExtract, GraphState


def test_us_full_pipeline_produces_artifacts():
    state = GraphState(
        filing_year=2024,
        jurisdictions=["US"],
        user_answers={"filing_status": "single", "num_dependents": "0", "state_of_residence": "CA"},
        extracts=[
            FormExtract(form_code="W-2", jurisdiction="US", fields={"wages": 80000.0, "federal_income_tax_withheld": 12000.0}),
            FormExtract(form_code="1099-INT", jurisdiction="US", fields={"interest_income": 500.0}),
        ],
    )

    state = reason_tax_node(state)
    with patch("wealthtax_agent.optimize._llm_rerank", side_effect=lambda x: x):
        state = optimize_node(state)
    state = build_return_node(state)

    assert "US" in state.draft_returns
    us = state.draft_returns["US"]
    assert us.total_income == 80500.0
    assert us.estimated_tax > 0

    assert "us_1040_pdf" in state.filing_artifacts
    assert "us_mef_json" in state.filing_artifacts

    mef = json.loads(base64.b64decode(state.filing_artifacts["us_mef_json"].content_b64))
    assert mef["transmissible"] is False
    assert mef["ReturnHeader"]["FilingStatus"] == "single"
