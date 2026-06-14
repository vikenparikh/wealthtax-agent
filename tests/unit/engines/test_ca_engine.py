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


def test_ca_provincial_donations_credit_uses_provincial_rate_ontario():
    """Ontario provincial donation credit: first $200 at 5.05%, excess at 11.16%
    (from the table) — not the federal 15%/29% amount. A $1,000 donation gives a
    provincial credit of 200*5.05% + 800*11.16% = $99.38 (was federal $262.00).

    FAILS before the fix: no provincial_donations_credit line item; provincial
    tax over-credited at federal donation rates."""
    extracts = [FormExtract(form_code="T4", jurisdiction="CA",
                            fields={"employment_income": 80000.0})]
    d = compute_ca_return(extracts, year=2024, province="ON",
                          user_answers={"charitable_donations": "1000"})
    expected = round(200 * 0.0505 + 800 * 0.1116, 2)  # 99.38
    assert round(d.line_items["provincial_donations_credit"], 2) == expected
    # Federal donation credit unchanged (15%/29%).
    assert round(d.line_items["donations_credit"], 2) == round(200 * 0.15 + 800 * 0.29, 2)  # 262.00


def test_ca_pension_income_amount_credited():
    """The pension income amount (federal line 31400) credits the first $2,000
    of eligible pension income (T4A superannuation, eligible at any age) at the
    lowest rate. The engine collected the income but never credited it.

    FAILS before the fix: no pension_income_credit line item and federal tax
    unchanged by pension income."""
    # $5,000 T4A pension -> capped at $2,000 -> 15% credit = $300.
    extracts = [FormExtract(form_code="T4A", jurisdiction="CA",
                            fields={"pension_or_superannuation": 5000.0})]
    d = compute_ca_return(extracts, year=2024, province="ON")
    assert round(d.line_items["pension_income_credit"], 2) == round(2000.0 * 0.15, 2)  # 300.00


def test_ca_pension_income_amount_below_cap_uses_full_amount():
    """Below the $2,000 cap the credit is on the full pension income."""
    extracts = [FormExtract(form_code="T4A", jurisdiction="CA",
                            fields={"pension_or_superannuation": 1200.0})]
    d = compute_ca_return(extracts, year=2024, province="ON")
    assert round(d.line_items["pension_income_credit"], 2) == round(1200.0 * 0.15, 2)  # 180.00


def test_ca_provincial_donations_credit_alberta_rate():
    """Alberta provincial donation credit: first $200 at 10% (lowest rate), excess
    at 21% (Alberta's legislated donation rate, above its top tax rate) — not the
    federal 15%/29% amount. A $1,000 donation -> 200*10% + 800*21% = $188.00.

    FAILS before the AB table gains donation_credit_high_rate (falls back to the
    federal-rate amount, $262)."""
    extracts = [FormExtract(form_code="T4", jurisdiction="CA",
                            fields={"employment_income": 80000.0})]
    d = compute_ca_return(extracts, year=2024, province="AB",
                          user_answers={"charitable_donations": "1000"})
    assert round(d.line_items["provincial_donations_credit"], 2) == round(200 * 0.10 + 800 * 0.21, 2)  # 188.00


def test_ca_rpp_and_union_dues_are_deducted():
    """RPP contributions (T4 box 20, line 20700) and union/professional dues
    (box 44, line 21200) reduce income. The extractor captured them but the
    engine ignored them, overstating taxable income for employees with a
    pension plan or union membership.

    FAILS before the fix: no rpp/union line items; taxable income unreduced."""
    base = [FormExtract(form_code="T4", jurisdiction="CA",
                        fields={"employment_income": 80000.0})]
    with_ded = [FormExtract(form_code="T4", jurisdiction="CA", fields={
        "employment_income": 80000.0,
        "rpp_contributions": 5000.0,
        "union_dues": 1200.0,
    })]
    d0 = compute_ca_return(base, year=2024, province="ON")
    d1 = compute_ca_return(with_ded, year=2024, province="ON")

    assert d1.line_items["rpp_deduction"] == 5000.0
    assert d1.line_items["union_dues_deduction"] == 1200.0
    # both reduce taxable income by their full amount (6200 total)
    assert d1.taxable_income == d0.taxable_income - 6200.0
    # and that lowers tax
    assert d1.estimated_tax < d0.estimated_tax
