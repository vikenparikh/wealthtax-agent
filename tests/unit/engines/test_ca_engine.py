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


def test_ca_cpp_ei_contributions_are_credited():
    """CPP and EI contributions (T4 boxes 16/18) are non-refundable credits at
    the lowest rate (lines 30800/31200). The engine collected them but never
    applied the credit, overstating federal tax for every employed Canadian.

    FAILS before the fix: no cpp_ei_credit line item and federal tax unchanged
    by the contributions."""
    base = [FormExtract(form_code="T4", jurisdiction="CA",
                        fields={"employment_income": 60000.0})]
    with_contrib = [FormExtract(form_code="T4", jurisdiction="CA", fields={
        "employment_income": 60000.0,
        "cpp_contributions": 3000.0,
        "ei_premiums": 900.0,
    })]
    d0 = compute_ca_return(base, year=2024, province="ON")
    d1 = compute_ca_return(with_contrib, year=2024, province="ON")

    assert d1.line_items["cpp_ei_credit"] == round((3000.0 + 900.0) * 0.15, 2)  # 585.00
    # The credit reduces federal tax relative to the same income without it.
    assert d1.line_items["federal_tax"] < d0.line_items["federal_tax"]
    assert round(d0.line_items["federal_tax"] - d1.line_items["federal_tax"], 2) == 585.0


def test_ca_provincial_cpp_ei_contributions_are_credited():
    """CPP/EI contributions are credited provincially too, at the province's
    lowest rate (ON 5.05%). The provincial credit block omitted them, so every
    ON T4 filer's provincial tax was overstated (~$197 for this case).

    FAILS before the fix: no provincial_cpp_ei_credit line item and provincial
    tax unchanged by the contributions."""
    base = [FormExtract(form_code="T4", jurisdiction="CA",
                        fields={"employment_income": 60000.0})]
    with_contrib = [FormExtract(form_code="T4", jurisdiction="CA", fields={
        "employment_income": 60000.0,
        "cpp_contributions": 3000.0,
        "ei_premiums": 900.0,
    })]
    d0 = compute_ca_return(base, year=2024, province="ON")
    d1 = compute_ca_return(with_contrib, year=2024, province="ON")

    assert round(d1.line_items["provincial_cpp_ei_credit"], 2) == 196.95
    assert round(d0.line_items["provincial_tax"] - d1.line_items["provincial_tax"], 2) == 196.95


def test_ca_provincial_medical_credit_uses_provincial_rate():
    """The provincial medical-expense credit must use the province's lowest rate
    (ON 5.05%), not the federal 15% amount. T4 net income $60k, $5,000 medical:
    creditable = 5000 - min(3% * 60000, 2759) = 5000 - 1800 = 3200, so the
    provincial credit is 3200 * 5.05% = $161.60 (was federal 3200 * 15% = $480).

    FAILS before the fix: no provincial_medical_credit line item; provincial tax
    over-credited at the federal rate."""
    extracts = [FormExtract(form_code="T4", jurisdiction="CA",
                            fields={"employment_income": 60000.0})]
    d = compute_ca_return(extracts, year=2024, province="ON",
                          user_answers={"medical_expenses": "5000"})
    assert round(d.line_items["provincial_medical_credit"], 2) == round(3200.0 * 0.0505, 2)  # 161.60
    # Federal medical credit is unchanged at the federal lowest rate.
    assert round(d.line_items["medical_credit"], 2) == round(3200.0 * 0.15, 2)  # 480.00
