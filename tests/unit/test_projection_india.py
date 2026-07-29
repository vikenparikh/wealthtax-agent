"""India projections must use the INDIA engine.

Regression: project_future_years only imported ca_engine + us_engine and routed
`if CA … else US`, so an IN return fell into the `else` and ran Form-16 extracts
through compute_us_return (which finds no W-2) → $0 income and $0 tax for every
projected year. An Indian filer got a garbage all-zero 5-year projection.
"""
from wealthtax_agent.engines.in_engine import compute_in_return
from wealthtax_agent.projection import project_future_years
from wealthtax_agent.state import FormExtract, GraphState


def _in_state(gross=1_500_000.0):
    ext = [FormExtract(form_code="FORM-16", jurisdiction="IN", fields={"gross_salary": gross})]
    return GraphState(
        filing_year=2024,
        jurisdictions=["IN"],
        user_answers={"in_regime": "auto", "age": "30"},
        extracts=ext,
        draft_returns={"IN": compute_in_return(ext, year=2024, regime="auto",
                                                residency_status="ROR", user_answers={"age": "30"})},
    )


def test_india_projection_uses_india_engine_not_zeros():
    proj = project_future_years(_in_state(), growth=0.05, horizon=5)
    assert set(proj.keys()) == {"IN"}
    rows = proj["IN"]
    assert len(rows) == 5
    for r in rows:
        # Pre-fix these were all 0.0 (US engine on Form-16 extracts).
        assert r["total_income"] > 1_000_000, f"IN projection income wrong: {r}"
        assert r["total_tax"] > 0, f"IN projection tax should be positive: {r}"


def test_india_projection_income_and_tax_grow():
    rows = project_future_years(_in_state(), growth=0.10, horizon=3)["IN"]
    assert rows[0]["total_income"] < rows[1]["total_income"] < rows[2]["total_income"]
    assert rows[0]["total_tax"] <= rows[1]["total_tax"] <= rows[2]["total_tax"]
