"""Artifact currency symbol must match jurisdiction.

Pre-registered bug (rung-3): the planning + amendment artifact-text builders in
``build_return.py`` hardcode ``$`` for ALL jurisdictions, but India amounts are
in rupees (₹). So an IN filer's planning and amendment draft artifacts show
rupee figures with a dollar sign. CA/US correctly use ``$``; only IN is wrong.
"""

import base64

from wealthtax_agent.build_return import _amendment_artifacts, _planning_artifact
from wealthtax_agent.state import DraftReturn, GraphState


def _decode(artifact):
    return base64.b64decode(artifact.content_b64).decode("utf-8")


def _planning_state(jurisdiction):
    draft = DraftReturn(
        jurisdiction=jurisdiction,
        totals={
            "total_income": 1200000 if jurisdiction == "IN" else 80000,
            "taxable_income": 1100000 if jurisdiction == "IN" else 70000,
            "total_tax": 150000 if jurisdiction == "IN" else 12000,
            "refund": 0,
            "balance_owing": 0,
        },
    )
    return GraphState(filing_year=2024, draft_returns={jurisdiction: draft})


def _amendment_state(jurisdiction):
    draft = DraftReturn(
        jurisdiction=jurisdiction,
        totals={
            "total_income": 1200000 if jurisdiction == "IN" else 80000,
            "taxable_income": 1100000 if jurisdiction == "IN" else 70000,
            "total_tax": 150000 if jurisdiction == "IN" else 12000,
            "refund": 0,
            "balance_owing": 0,
        },
    )
    return GraphState(
        filing_year=2024,
        draft_returns={jurisdiction: draft},
        is_amendment=True,
        prior_filed_totals={
            jurisdiction: {
                "total_income": 1100000 if jurisdiction == "IN" else 75000,
                "taxable_income": 1000000 if jurisdiction == "IN" else 65000,
                "total_tax": 140000 if jurisdiction == "IN" else 11000,
                "refund": 0,
                "balance_owing": 0,
            }
        },
    )


# --- IN: must use rupee symbol -------------------------------------------------


def test_in_planning_artifact_uses_rupee():
    text = _decode(_planning_artifact(_planning_state("IN")))
    # filed-year totals line for IN must carry ₹, not $
    totals_lines = [ln for ln in text.splitlines() if "Total income:" in ln]
    assert totals_lines, "expected a filed-year totals line"
    assert "₹" in totals_lines[0]
    assert "$" not in totals_lines[0]


def test_in_amendment_artifact_uses_rupee():
    out = _amendment_artifacts(_amendment_state("IN"))
    text = _decode(out["in_amendment"])
    figure_lines = [ln for ln in text.splitlines() if ln.startswith("total_income")]
    assert figure_lines, "expected a three-column figure row"
    assert "₹" in figure_lines[0]
    assert "$" not in figure_lines[0]


# --- US / CA: regression guards — must still use dollar ------------------------


def test_us_planning_artifact_uses_dollar():
    text = _decode(_planning_artifact(_planning_state("US")))
    totals_lines = [ln for ln in text.splitlines() if "Total income:" in ln]
    assert totals_lines
    assert "$" in totals_lines[0]
    assert "₹" not in totals_lines[0]


def test_ca_planning_artifact_uses_dollar():
    text = _decode(_planning_artifact(_planning_state("CA")))
    totals_lines = [ln for ln in text.splitlines() if "Total income:" in ln]
    assert totals_lines
    assert "$" in totals_lines[0]
    assert "₹" not in totals_lines[0]


def test_us_amendment_artifact_uses_dollar():
    out = _amendment_artifacts(_amendment_state("US"))
    text = _decode(out["us_amendment"])
    figure_lines = [ln for ln in text.splitlines() if ln.startswith("total_income")]
    assert figure_lines
    assert "$" in figure_lines[0]
    assert "₹" not in figure_lines[0]


def test_ca_amendment_artifact_uses_dollar():
    out = _amendment_artifacts(_amendment_state("CA"))
    text = _decode(out["ca_amendment"])
    figure_lines = [ln for ln in text.splitlines() if ln.startswith("total_income")]
    assert figure_lines
    assert "$" in figure_lines[0]
    assert "₹" not in figure_lines[0]
