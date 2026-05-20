"""User-requested scenario: worked in US for 5 months, moved to Canada for the
rest of the year, vacation in India for 1 month.

Inputs:
  - 5 months in the US — W-2 wages $60k + 1098-E $1,200 student loan interest
  - 7 months in Canada — T4 employment income $70k (+ CPP/EI captured but not added back)
  - 1 month in India — vacation, no Indian income

Residency expectations:
  - US: nonresident (~152 days, no prior US presence)
  - CA: part-year resident (factual ties established mid-year)
  - IN: NR (30 days < 60-day threshold)

Engine expectations:
  - US 1040-NR-style draft on the W-2 income only
  - CA T1 includes the T4 income only; the engine emits a part-year note
  - No IN draft (NR with zero IN-source income)

Cross-border:
  - Student loan claimed only in the US (higher marginal); CA branch should not claim it
"""

from wealthtax_agent.state import FormExtract


def test_us_to_ca_with_india_vacation(build_state, run_graph):
    extracts = [
        FormExtract(form_code="W-2", jurisdiction="US",
                    fields={"wages": 60000.0, "federal_income_tax_withheld": 8000.0}),
        FormExtract(form_code="1098-E", jurisdiction="US",
                    fields={"student_loan_interest": 1200.0}),
        FormExtract(form_code="T4", jurisdiction="CA",
                    fields={"employment_income": 70000.0, "income_tax_deducted": 12000.0,
                            "cpp_contributions": 3500.0, "ei_premiums": 1200.0}),
    ]
    state = build_state(
        jurisdictions=["US", "CA"],
        extracts=extracts,
        residency_days={"US": 152, "CA": 213, "IN": 30},
        user_answers={
            "filing_status": "single",
            "state_of_residence": "CA",
            "province_of_residence": "ON",
            "num_dependents": "0",
            "moved_country_during_year": "yes",
            "has_primary_ties_ca": "yes",  # established after the move
            "student_loan_country": "US",
        },
        filing_year=2024,
    )

    result = run_graph(state)

    # ---- Residency ----
    assert result.residency_status["US"] == "nonresident"
    assert result.residency_status["CA"] == "part_year_resident"
    assert result.residency_status["IN"] == "NR"
    # Should NOT include India in drafts (the user didn't add IN to jurisdictions)
    assert "IN" not in result.draft_returns

    # ---- US draft ----
    us = result.draft_returns["US"]
    assert us.line_items["wages"] == 60000.0
    # Student loan claimed in US (only jurisdiction claiming it)
    assert us.line_items["student_loan_interest_deduction"] == 1200.0

    # ---- CA draft ----
    ca = result.draft_returns["CA"]
    assert ca.line_items["employment_income"] == 70000.0
    # CA didn't claim student loan (user routed it to US)
    assert ca.line_items.get("student_loan_interest_ca", 0) == 0

    # ---- Cross-border warnings ----
    warnings_blob = " ".join(result.warnings)
    assert "Cross-border" in warnings_blob
    # Part-year resident note from CA engine
    assert any("part-year" in n.lower() for n in ca.notes)
    # US 1040-NR / nonresident note from US engine
    assert any("nonresident" in n.lower() for n in us.notes)


def test_student_loan_claimed_in_two_jurisdictions_only_one_kept(build_state, run_graph):
    """User accidentally lists student loan interest in both 1098-E and CA section.

    The cross-border guardrail zeros out the lower-marginal jurisdiction
    and surfaces a warning.
    """
    extracts = [
        FormExtract(form_code="W-2", jurisdiction="US",
                    fields={"wages": 120000.0}),
        FormExtract(form_code="1098-E", jurisdiction="US",
                    fields={"student_loan_interest": 2500.0}),
        FormExtract(form_code="T4", jurisdiction="CA",
                    fields={"employment_income": 80000.0}),
    ]
    state = build_state(
        jurisdictions=["US", "CA"],
        extracts=extracts,
        residency_days={"US": 200, "CA": 220},
        user_answers={
            "filing_status": "single",
            "state_of_residence": "CA",
            "province_of_residence": "ON",
            "has_primary_ties_ca": "yes",
            "student_loan_interest_ca": "2500",  # user mistakenly enters it in CA too
        },
    )

    result = run_graph(state)
    warnings_blob = " ".join(result.warnings)
    assert "student-loan" in warnings_blob.lower()
    # The lower-marginal jurisdiction's claim should now be zero
    us_claim = result.draft_returns["US"].line_items.get("student_loan_interest_deduction", 0)
    ca_claim = result.draft_returns["CA"].line_items.get("student_loan_interest_ca", 0)
    assert (us_claim == 0) ^ (ca_claim == 0)
