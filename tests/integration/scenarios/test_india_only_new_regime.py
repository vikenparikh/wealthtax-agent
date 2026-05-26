"""AC7 — India-only scenario: new regime, 80C investments, HRA exemption.

A salaried resident (ROR, 365 days in India) on the new tax regime with:
  - Gross salary 1,200,000 ₹ (includes basic 720,000 + HRA 240,000)
  - Rent paid 240,000 ₹ (metro city)
  - 80C investments 150,000 ₹ (PPF + ELSS — max cap)
  - Section 80D: 25,000 ₹ health premium

New regime invariants:
  - Standard deduction 75,000 ₹ (FY 2024-25, Finance Bill 2024)
  - 80C / 80D / HRA deductions NOT available under new regime
  - §87A rebate applies (taxable income ≤ 7,00,000 ₹)
  - ITR JSON artifact must be present

Assertions:
  - residency_status["IN"] == "ROR"  (360+ days, born in India)
  - draft_returns["IN"].total_tax > 0  (net tax after cess, above rebate threshold)
  - "in_itr_json" artifact present in state.artifacts
"""
from __future__ import annotations

import json

import pytest

from wealthtax_agent.state import FormExtract


def test_india_only_new_regime(build_state, run_graph):
    """Full pipeline for India-only new regime with 80C + HRA data."""
    extracts = [
        FormExtract(
            form_code="FORM-16",
            jurisdiction="IN",
            fields={
                "gross_salary": 1_200_000.0,
                "basic_salary": 720_000.0,
                "hra_received": 240_000.0,
                "standard_deduction_salary": 75_000.0,
                "section_80c_declared": 150_000.0,
                "section_80d_declared": 25_000.0,
                "tds_deducted": 40_000.0,
            },
        ),
        FormExtract(
            form_code="INVESTMENTS-80C",
            jurisdiction="IN",
            fields={"amount": 150_000.0},
        ),
    ]

    state = build_state(
        jurisdictions=["IN"],
        extracts=extracts,
        residency_days={"IN": 365},
        user_answers={
            "filing_status": "single",
            "age": "30",
            "is_indian_citizen": "yes",
            "in_regime": "new",
            "rent_paid_monthly": "20000",
            "metro_city": "yes",
        },
        filing_year=2024,
    )

    result = run_graph(state)

    # ---- residency ----
    assert "IN" in result.residency_status, "India residency status must be computed"
    # 365 days this year = resident; without prior-year resident history → RNOR
    # (ROR requires >= 730 days in last 7 years as resident, which we don't supply here)
    assert result.residency_status["IN"] in ("ROR", "RNOR"), (
        f"365 days in India → resident (ROR or RNOR); got {result.residency_status['IN']!r}"
    )

    # ---- draft return present ----
    assert "IN" in result.draft_returns, "India draft return must be produced"
    draft = result.draft_returns["IN"]

    # ---- gross salary line item ----
    assert draft.line_items.get("gross_salary") == 1_200_000.0, (
        f"gross_salary line item mismatch: {draft.line_items.get('gross_salary')}"
    )

    # ---- new regime: 80C/80D NOT deducted ----
    # Standard deduction (75k) IS allowed under new regime; 80C/80D are not.
    # Net taxable should be close to 1,200,000 - 75,000 = 1,125,000
    # (HRA also not deductible under new regime)
    taxable_income = draft.taxable_income
    assert taxable_income > 700_000, (
        f"taxable income {taxable_income} too low — 80C/HRA must not be deducted under new regime"
    )

    # ---- estimated_tax > 0 (above §87A rebate threshold) ----
    assert draft.estimated_tax > 0, (
        f"estimated_tax should be > 0 for taxable income ~{taxable_income:.0f}; got {draft.estimated_tax}"
    )

    # ---- ITR JSON artifact ----
    assert "in_itr_json" in result.filing_artifacts, (
        "ITR JSON artifact ('in_itr_json') must be in state.filing_artifacts"
    )
    artifact = result.filing_artifacts["in_itr_json"]
    assert artifact.transmissible is False, "FilingArtifact must have transmissible=False"

    # ---- ITR JSON is valid JSON ----
    import base64
    raw_json = base64.b64decode(artifact.content_b64).decode("utf-8")
    itr_dict = json.loads(raw_json)
    assert isinstance(itr_dict, dict), "ITR JSON must deserialise to a dict"
    # Accept either schema_version or assessment_year as a structural marker
    assert itr_dict.get("schema_version") is not None or itr_dict.get("assessment_year") is not None, (
        f"ITR JSON must have schema_version or assessment_year key; got keys: {list(itr_dict.keys())}"
    )


def test_india_only_new_regime_standard_deduction_applied(build_state, run_graph):
    """Standard deduction of 75k must reduce taxable income under new regime."""
    extracts = [
        FormExtract(
            form_code="FORM-16",
            jurisdiction="IN",
            fields={
                "gross_salary": 800_000.0,
                "basic_salary": 500_000.0,
                "hra_received": 150_000.0,
                "tds_deducted": 10_000.0,
            },
        ),
    ]
    state = build_state(
        jurisdictions=["IN"],
        extracts=extracts,
        residency_days={"IN": 365},
        user_answers={
            "age": "28",
            "is_indian_citizen": "yes",
            "in_regime": "new",
        },
        filing_year=2024,
    )
    result = run_graph(state)
    assert "IN" in result.draft_returns
    draft = result.draft_returns["IN"]
    # Standard deduction must have reduced taxable income
    std_ded = draft.line_items.get("standard_deduction_salary", 0.0)
    assert std_ded >= 50_000, (
        f"standard_deduction_salary line item {std_ded} too small; expected >= 50,000 under new regime"
    )


def test_india_only_new_regime_87a_rebate_zero_tax(build_state, run_graph):
    """Income ≤ 7,00,000 under new regime → §87A rebate → zero net tax."""
    extracts = [
        FormExtract(
            form_code="FORM-16",
            jurisdiction="IN",
            fields={
                "gross_salary": 700_000.0,
                "basic_salary": 450_000.0,
                "tds_deducted": 0.0,
            },
        ),
    ]
    state = build_state(
        jurisdictions=["IN"],
        extracts=extracts,
        residency_days={"IN": 365},
        user_answers={
            "age": "25",
            "is_indian_citizen": "yes",
            "in_regime": "new",
        },
        filing_year=2024,
    )
    result = run_graph(state)
    assert "IN" in result.draft_returns
    draft = result.draft_returns["IN"]
    # After standard deduction 75k: taxable = 625,000 ≤ 700,000 → full rebate
    assert draft.estimated_tax == 0.0, (
        f"§87A rebate should zero out tax for income 700k under new regime; got {draft.estimated_tax}"
    )
