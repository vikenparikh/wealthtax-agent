from wealthtax_agent.engines.ca_engine import compute_ca_return
from wealthtax_agent.state import FormExtract


def test_ca_engine_t4_only_2024_single():
    extracts = [
        FormExtract(form_code="T4", jurisdiction="CA", fields={
            "employment_income": 60000.0,
            "income_tax_deducted": 10000.0,
            "cpp_contributions": 3000.0,
            "ei_premiums": 900.0,
        }),
    ]
    draft = compute_ca_return(extracts, year=2024, province="ON")

    assert draft.jurisdiction == "CA"
    assert draft.total_income == 60000.0
    assert draft.taxable_income == 60000.0
    assert draft.line_items["federal_tax"] > 0
    assert draft.line_items["provincial_tax"] > 0
    # Should be close to a sane order of magnitude
    assert 6000 < draft.estimated_tax < 12000


def test_ca_engine_t4_t5_rrsp_combined():
    extracts = [
        FormExtract(form_code="T4", jurisdiction="CA", fields={"employment_income": 80000.0, "income_tax_deducted": 14500.0}),
        FormExtract(form_code="T5", jurisdiction="CA", fields={"interest_income": 1200.0, "taxable_eligible_dividends": 1380.0}),
        FormExtract(form_code="RRSP", jurisdiction="CA", fields={"rrsp_contributions": 7000.0}),
    ]
    draft = compute_ca_return(extracts, year=2024, province="ON")

    assert draft.rrsp_deduction == 7000.0
    assert draft.taxable_income == 80000.0 + 1200.0 + 1380.0 - 7000.0
    assert draft.estimated_tax > 0


def test_ca_engine_t5008_capital_gains_50pct_inclusion():
    extracts = [
        FormExtract(form_code="T5008", jurisdiction="CA", fields={"capital_gain": 10000.0}),
    ]
    draft = compute_ca_return(extracts, year=2024, province="ON")
    assert draft.line_items["taxable_capital_gains"] == 5000.0


def test_ca_engine_missing_year_records_note():
    extracts = [
        FormExtract(form_code="T4", jurisdiction="CA", fields={"employment_income": 50000.0}),
    ]
    draft = compute_ca_return(extracts, year=1999)
    assert any("missing" in n.lower() for n in draft.notes)
