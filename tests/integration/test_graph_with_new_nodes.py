"""Verify the new dedupe + residency nodes don't break the existing pipeline."""

from wealthtax_agent.graph import build_graph
from wealthtax_agent.state import FormExtract, GraphState


def _run(state: GraphState) -> GraphState:
    return GraphState.model_validate(build_graph().invoke(state))


def test_pipeline_without_residency_days_still_works():
    """Pre-existing flow: no residency_days set → residency_test_node no-ops."""
    state = GraphState(
        jurisdictions=["US"],
        extracts=[FormExtract(form_code="W-2", jurisdiction="US", fields={"wages": 50000.0})],
        user_answers={"filing_status": "single", "state_of_residence": "CA"},
        filing_year=2024,
    )
    result = _run(state)
    assert result.residency_status == {}
    assert "US" in result.draft_returns


def test_pipeline_dedupe_removes_repeated_form_in_state():
    """Two identical W-2 extracts → only one survives the pipeline."""
    base = FormExtract(form_code="W-2", jurisdiction="US",
                       fields={"wages": 50000.0},
                       text_fields={"payer_name": "Acme"})
    state = GraphState(
        jurisdictions=["US"],
        extracts=[base.model_copy(deep=True), base.model_copy(deep=True)],
        user_answers={"filing_status": "single", "state_of_residence": "CA"},
        filing_year=2024,
    )
    result = _run(state)
    w2_count = sum(1 for e in result.extracts if e.form_code == "W-2")
    assert w2_count == 1
    assert any("Duplicate form skipped" in w for w in result.warnings)


def test_pipeline_residency_test_fires_when_days_set():
    state = GraphState(
        jurisdictions=["US"],
        extracts=[FormExtract(form_code="W-2", jurisdiction="US", fields={"wages": 50000.0})],
        residency_days={"US": 250},
        user_answers={"filing_status": "single", "state_of_residence": "CA"},
        filing_year=2024,
    )
    result = _run(state)
    assert result.residency_status["US"] == "resident"


def test_pipeline_in_only_filing_year_2024():
    state = GraphState(
        jurisdictions=["IN"],
        extracts=[FormExtract(form_code="FORM-16", jurisdiction="IN",
                              fields={"gross_salary": 1000000, "tds_deducted": 50000})],
        residency_days={"IN": 300},
        user_answers={"age": "30", "in_regime": "new", "is_indian_citizen": "yes"},
        filing_year=2024,
    )
    result = _run(state)
    assert result.residency_status["IN"] in {"ROR", "RNOR"}
    assert "IN" in result.draft_returns
    assert any(k.startswith("in_itr") for k in result.filing_artifacts)
