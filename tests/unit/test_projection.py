from wealthtax_agent.engines.ca_engine import compute_ca_return
from wealthtax_agent.engines.us_engine import compute_us_return
from wealthtax_agent.projection import project_future_years
from wealthtax_agent.state import FormExtract, GraphState


def test_projects_5_years_for_each_jurisdiction():
    ca_extracts = [FormExtract(form_code="T4", jurisdiction="CA", fields={"employment_income": 80000.0})]
    us_extracts = [FormExtract(form_code="W-2", jurisdiction="US", fields={"wages": 80000.0})]
    state = GraphState(
        filing_year=2024,
        jurisdictions=["CA", "US"],
        user_answers={"province_of_residence": "ON", "filing_status": "single", "state_of_residence": "CA"},
        extracts=ca_extracts + us_extracts,
        draft_returns={
            "CA": compute_ca_return(ca_extracts, year=2024, province="ON"),
            "US": compute_us_return(us_extracts, year=2024, state="CA", user_answers={"filing_status": "single"}),
        },
    )

    projection = project_future_years(state, growth=0.05, horizon=5)
    assert set(projection.keys()) == {"CA", "US"}
    for jurisdiction, rows in projection.items():
        assert len(rows) == 5
        for row in rows:
            assert row["total_income"] > 0
            assert row["taxable_income"] >= 0
            assert row["total_tax"] >= 0


def test_projection_income_grows_year_over_year():
    extracts = [FormExtract(form_code="T4", jurisdiction="CA", fields={"employment_income": 50000.0})]
    state = GraphState(
        filing_year=2024,
        jurisdictions=["CA"],
        user_answers={"province_of_residence": "ON"},
        extracts=extracts,
        draft_returns={"CA": compute_ca_return(extracts, year=2024, province="ON")},
    )
    proj = project_future_years(state, growth=0.10, horizon=3)["CA"]
    assert proj[0]["total_income"] < proj[1]["total_income"] < proj[2]["total_income"]


def test_projection_falls_back_to_current_tables_when_year_missing():
    extracts = [FormExtract(form_code="T4", jurisdiction="CA", fields={"employment_income": 50000.0})]
    state = GraphState(
        filing_year=2025,  # we only ship through 2025; horizon=5 reaches 2030
        jurisdictions=["CA"],
        user_answers={"province_of_residence": "ON"},
        extracts=extracts,
        draft_returns={"CA": compute_ca_return(extracts, year=2025, province="ON")},
    )
    proj = project_future_years(state, growth=0.03, horizon=5)["CA"]
    assert len(proj) == 5  # falls back gracefully
