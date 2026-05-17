"""Advanced CA engine tests: OAS clawback, donations / medical credits,
T1135 awareness, T2222 Northern Residents Deduction."""

from wealthtax_agent.engines.ca_engine import compute_ca_return
from wealthtax_agent.state import FormExtract


def _t4(wages: float) -> FormExtract:
    return FormExtract(form_code="T4", jurisdiction="CA", fields={"employment_income": wages})


def test_donations_credit_applied():
    extracts = [_t4(80000.0)]
    draft_no = compute_ca_return(extracts, year=2024, province="ON")
    draft_yes = compute_ca_return(
        extracts, year=2024, province="ON",
        user_answers={"charitable_donations": "2000"},
    )
    # Donations credit reduces federal + provincial tax
    assert draft_yes.estimated_tax < draft_no.estimated_tax
    assert draft_yes.line_items["donations_credit"] > 0


def test_medical_credit_applied_above_threshold():
    extracts = [_t4(80000.0)]
    # 3% of 80000 = 2400 threshold, so $5000 - $2400 = $2600 creditable
    draft = compute_ca_return(
        extracts, year=2024, province="ON",
        user_answers={"medical_expenses": "5000"},
    )
    assert draft.line_items["medical_credit"] > 0


def test_oas_clawback_when_pension_income_pushes_over_threshold():
    extracts = [
        FormExtract(form_code="T4A", jurisdiction="CA", fields={"pension_or_superannuation": 100000.0}),
        FormExtract(form_code="T4", jurisdiction="CA", fields={"employment_income": 30000.0}),
    ]
    draft = compute_ca_return(extracts, year=2024, province="ON")
    assert draft.line_items["oas_clawback"] > 0
    assert any("OAS" in n or "clawback" in n for n in draft.notes)


def test_t1135_reminder_emitted_for_foreign_property_over_100k():
    extracts = [
        _t4(80000.0),
        FormExtract(form_code="T1135", jurisdiction="CA", fields={"total_foreign_property_cost": 250000.0}),
    ]
    draft = compute_ca_return(extracts, year=2024, province="ON")
    assert draft.line_items["t1135_foreign_property_cost"] == 250000.0
    assert any("T1135" in n for n in draft.notes)


def test_t2222_northern_residents_deduction_reduces_net_income():
    extracts = [
        _t4(60000.0),
        FormExtract(form_code="T2222", jurisdiction="CA", fields={
            "residency_deduction": 4015.0,
            "travel_deduction": 1200.00,
        }),
    ]
    draft = compute_ca_return(extracts, year=2024, province="ON")
    assert draft.line_items["northern_residents_deduction"] == 5215.0
    assert draft.taxable_income == 60000.0 - 5215.0


def test_bc_province_table_loads_and_taxes_computed():
    extracts = [_t4(80000.0)]
    draft = compute_ca_return(extracts, year=2024, province="BC")
    assert draft.line_items["provincial_tax"] > 0


def test_qc_emits_separate_filing_note():
    extracts = [_t4(60000.0)]
    draft = compute_ca_return(extracts, year=2024, province="QC")
    assert any("Quebec" in n or "Québec" in n for n in draft.notes)
