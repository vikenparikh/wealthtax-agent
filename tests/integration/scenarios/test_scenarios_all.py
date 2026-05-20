"""Additional real-life cross-border scenarios beyond the two top-priority ones.

Each scenario asserts:
- Per-jurisdiction residency status string
- Per-jurisdiction draft is generated when expected
- Presence of treaty / FTC / sourcing hints in warnings
- Key engine line items match the worked example
"""

import pytest

from wealthtax_agent.state import FormExtract


# ---------- Scenario: Indian citizen on H1B returning to India ----------

def test_indian_citizen_h1b_to_india(build_state, run_graph):
    """Worked in US Jan-Aug (180 days), returned to India Sep-Dec (124 days)."""
    extracts = [
        FormExtract(form_code="W-2", jurisdiction="US",
                    fields={"wages": 100000.0, "federal_income_tax_withheld": 18000.0}),
        FormExtract(form_code="FORM-16", jurisdiction="IN",
                    fields={"gross_salary": 600000.0, "tds_deducted": 50000.0}),
    ]
    state = build_state(
        jurisdictions=["US", "IN"],
        extracts=extracts,
        residency_days={"US": 180, "IN": 124},
        user_answers={
            "filing_status": "single",
            "state_of_residence": "CA",
            "is_indian_citizen": "yes",
            "moved_country_during_year": "yes",
            "age": "32",
            "in_regime": "new",
            # Prior H1B years: full presence
            "prior_year_days_us_prior_1": "365",
            "prior_year_days_us_prior_2": "365",
        },
    )
    result = run_graph(state)
    # 180 current + 365/3 + 365/6 = 180 + 121.67 + 60.83 = 362.5 ≥ 183 → SPT met
    # Plus moved_country_during_year → dual_status
    assert result.residency_status["US"] == "dual_status"
    # India: 124 days current, no prior history → NR (needs 60+/365 prior or 182+)
    assert result.residency_status["IN"] == "NR"

    # Both drafts present
    assert "US" in result.draft_returns
    assert "IN" in result.draft_returns
    # India draft taxes the gross salary (Indian-source from Indian employer)
    assert result.draft_returns["IN"].line_items["gross_salary"] == 600000.0


# ---------- Scenario: US citizen living in Canada ----------

def test_us_citizen_living_in_canada_all_year(build_state, run_graph):
    """US citizen, Canadian resident all year, T4 wages.

    US: citizen → always resident → must file 1040 but Form 2555 FEIE applies.
    CA: full T1 resident return.
    Cross-border: only one student-loan claim allowed.
    """
    extracts = [
        FormExtract(form_code="T4", jurisdiction="CA",
                    fields={"employment_income": 100000.0, "income_tax_deducted": 22000.0}),
        FormExtract(form_code="2555", jurisdiction="US",
                    fields={"foreign_earned_income": 100000.0,
                            "foreign_earned_income_excluded": 100000.0}),
    ]
    state = build_state(
        jurisdictions=["US", "CA"],
        extracts=extracts,
        residency_days={"US": 0, "CA": 365},
        user_answers={
            "filing_status": "single",
            "state_of_residence": "CA",
            "province_of_residence": "ON",
            "is_us_citizen": "yes",
            "is_us_person": "yes",
            "has_primary_ties_ca": "yes",
        },
    )
    result = run_graph(state)
    assert result.residency_status["US"] == "resident"  # citizen rule
    assert result.residency_status["CA"] == "resident"

    us = result.draft_returns["US"]
    # FEIE excludes foreign-earned income; effective US tax should be small.
    assert us.line_items["feie_excluded"] == 100000.0

    ca = result.draft_returns["CA"]
    assert ca.line_items["employment_income"] == 100000.0


# ---------- Scenario: Canadian cross-border worker (commuter to US) ----------

def test_canadian_resident_with_us_wages(build_state, run_graph):
    """Canadian resident, ~160 days physical presence in US, W-2 wages."""
    extracts = [
        FormExtract(form_code="W-2", jurisdiction="US",
                    fields={"wages": 90000.0, "federal_income_tax_withheld": 12000.0}),
    ]
    state = build_state(
        jurisdictions=["US", "CA"],
        extracts=extracts,
        residency_days={"US": 160, "CA": 360},
        user_answers={
            "filing_status": "single",
            "state_of_residence": "NY",
            "province_of_residence": "ON",
            "has_primary_ties_ca": "yes",
        },
    )
    result = run_graph(state)
    assert result.residency_status["US"] == "nonresident"  # SPT requires 183 weighted
    assert result.residency_status["CA"] == "resident"

    # US 1040-NR style — wages still taxed on US side
    assert result.draft_returns["US"].line_items["wages"] == 90000.0
    # Cross-border warning surfaces FTC hint
    assert any("Foreign tax credit" in w for w in result.warnings)


# ---------- Scenario: India ROR with US brokerage dividends ----------

def test_indian_resident_with_us_brokerage(build_state, run_graph):
    """India ROR receives 1099-DIV $2000 + $1500 qualified.

    US engine treats as nonresident withholding; India engine includes as
    Other Sources at slab rates; FTC hint covers the US withholding.
    """
    extracts = [
        FormExtract(form_code="1099-DIV", jurisdiction="US",
                    fields={"ordinary_dividends": 2000.0,
                            "qualified_dividends": 1500.0,
                            "federal_income_tax_withheld": 500.0}),
        FormExtract(form_code="FORM-16", jurisdiction="IN",
                    fields={"gross_salary": 1500000.0, "tds_deducted": 150000.0}),
    ]
    state = build_state(
        jurisdictions=["US", "IN"],
        extracts=extracts,
        residency_days={"US": 5, "IN": 360},
        user_answers={
            "filing_status": "single",
            "state_of_residence": "NY",
            "is_indian_citizen": "yes",
            "age": "35",
            "in_regime": "old",
            "dividend_income": "166000",  # ~$2000 in INR for the India engine
        },
    )
    state.user_answers["prior_year_days_in_prior_7_days"] = "1500"  # ROR
    result = run_graph(state)
    assert result.residency_status["US"] == "nonresident"
    # India: 360 days current, with ample prior history → ROR
    assert result.residency_status["IN"] in {"ROR", "RNOR"}

    # Both drafts produced
    assert "US" in result.draft_returns
    assert "IN" in result.draft_returns
    # India ITR JSON artifact appears
    in_artifacts = [k for k in result.filing_artifacts if k.startswith("in_")]
    assert in_artifacts


# ---------- Scenario: Dual-status year (US→IN move) ----------

def test_dual_status_year_us_to_india(build_state, run_graph):
    """US resident Jan-Jun, moves to India permanently in July."""
    extracts = [
        FormExtract(form_code="W-2", jurisdiction="US",
                    fields={"wages": 70000.0, "federal_income_tax_withheld": 10000.0}),
        FormExtract(form_code="FORM-16", jurisdiction="IN",
                    fields={"gross_salary": 600000.0, "tds_deducted": 40000.0}),
    ]
    state = build_state(
        jurisdictions=["US", "IN"],
        extracts=extracts,
        residency_days={"US": 180, "IN": 184},
        user_answers={
            "filing_status": "single",
            "state_of_residence": "CA",
            "is_indian_citizen": "yes",
            "moved_country_during_year": "yes",
            "age": "30",
            "in_regime": "new",
            "prior_year_days_us_prior_1": "365",
            "prior_year_days_us_prior_2": "365",
        },
    )
    result = run_graph(state)
    # US: 180 days current + heavy prior → SPT met + moved → dual_status
    assert result.residency_status["US"] == "dual_status"
    # India: 184 ≥ 182 → resident; with no prior 7-year presence → RNOR
    assert result.residency_status["IN"] in {"ROR", "RNOR"}

    # Treaty hint for US-India tie should appear
    assert any("US-India" in w for w in result.warnings)


# ---------- Scenario: 401(k) early withdrawal after emigration ----------

def test_401k_withdrawal_after_emigration(build_state, run_graph):
    """US person now Canadian resident takes $30k 401(k) distribution."""
    extracts = [
        FormExtract(form_code="1099-R", jurisdiction="US",
                    fields={"gross_distribution": 30000.0,
                            "taxable_amount": 30000.0,
                            "federal_income_tax_withheld": 6000.0}),
    ]
    state = build_state(
        jurisdictions=["US", "CA"],
        extracts=extracts,
        residency_days={"US": 0, "CA": 365},
        user_answers={
            "filing_status": "single",
            "is_us_citizen": "yes",
            "is_us_person": "yes",
            "province_of_residence": "ON",
            "has_primary_ties_ca": "yes",
            "age": "45",  # < 59.5 → early withdrawal
        },
    )
    result = run_graph(state)
    assert result.residency_status["US"] == "resident"  # citizen
    assert result.residency_status["CA"] == "resident"
    us = result.draft_returns["US"]
    assert us.line_items["taxable_pension"] == 30000.0  # 1099-R taxable_amount
    # FTC hint should surface
    assert any("Foreign tax credit" in w or "Cross-border" in w for w in result.warnings)


# ---------- Three-jurisdiction sanity test ----------

def test_three_jurisdiction_simultaneous_compute(build_state, run_graph):
    """User has income in all three jurisdictions in the same year."""
    extracts = [
        FormExtract(form_code="W-2", jurisdiction="US", fields={"wages": 50000.0}),
        FormExtract(form_code="T4", jurisdiction="CA", fields={"employment_income": 40000.0}),
        FormExtract(form_code="FORM-16", jurisdiction="IN", fields={"gross_salary": 800000.0, "tds_deducted": 50000.0}),
    ]
    state = build_state(
        jurisdictions=["US", "CA", "IN"],
        extracts=extracts,
        residency_days={"US": 100, "CA": 100, "IN": 165},
        user_answers={
            "filing_status": "single",
            "state_of_residence": "CA",
            "province_of_residence": "ON",
            "age": "30",
            "in_regime": "new",
            "is_indian_citizen": "yes",
        },
    )
    result = run_graph(state)
    # All three drafts present
    assert set(result.draft_returns.keys()) == {"US", "CA", "IN"}
    # Status set for all three
    assert "US" in result.residency_status
    assert "CA" in result.residency_status
    assert "IN" in result.residency_status

    # India ITR JSON exists
    assert any(k.startswith("in_itr") for k in result.filing_artifacts)
    # Canadian T1 PDF exists
    assert any(k == "ca_t1_pdf" for k in result.filing_artifacts)
    # US 1040 PDF exists
    assert any(k == "us_1040_pdf" for k in result.filing_artifacts)
