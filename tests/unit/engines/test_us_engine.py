from wealthtax_agent.engines.us_engine import compute_us_return
from wealthtax_agent.state import FormExtract


def test_us_engine_w2_only_single():
    extracts = [
        FormExtract(form_code="W-2", jurisdiction="US", fields={
            "wages": 80000.0,
            "federal_income_tax_withheld": 12000.0,
        }),
    ]
    draft = compute_us_return(extracts, year=2024, user_answers={"filing_status": "single", "num_dependents": "0"})

    assert draft.total_income == 80000.0
    # 2024 single std deduction = 14,600
    assert draft.line_items["standard_deduction"] == 14600.0
    assert draft.taxable_income == 80000.0 - 14600.0
    assert draft.line_items["federal_tax"] > 0


def test_us_engine_qualified_dividends_preferential_rate():
    extracts = [
        FormExtract(form_code="W-2", jurisdiction="US", fields={"wages": 50000.0}),
        FormExtract(form_code="1099-DIV", jurisdiction="US", fields={
            "ordinary_dividends": 2000.0,
            "qualified_dividends": 2000.0,
        }),
    ]
    draft = compute_us_return(extracts, year=2024, user_answers={"filing_status": "single"})
    # Ordinary tax computed on (taxable_income - qualified_dividends)
    # Preferential tax on the $2k qualified dividends
    assert draft.line_items["qualified_dividends"] == 2000.0
    assert draft.line_items["preferential_tax"] >= 0


def test_us_engine_child_tax_credit_applied():
    extracts = [
        FormExtract(form_code="W-2", jurisdiction="US", fields={"wages": 60000.0}),
    ]
    draft = compute_us_return(extracts, year=2024, user_answers={"filing_status": "single", "num_dependents": "2"})
    assert draft.credits["child_tax_credit"] == 4000.0


def test_us_engine_self_employment_tax_on_nec():
    extracts = [
        FormExtract(form_code="1099-NEC", jurisdiction="US", fields={"nonemployee_compensation": 30000.0}),
    ]
    draft = compute_us_return(extracts, year=2024, user_answers={"filing_status": "single"})
    assert draft.line_items["self_employment_tax"] > 0


def test_us_engine_state_tax_added_when_state_table_present():
    extracts = [
        FormExtract(form_code="W-2", jurisdiction="US", fields={"wages": 100000.0}),
    ]
    draft = compute_us_return(extracts, year=2024, state="CA", user_answers={"filing_status": "single"})
    assert draft.line_items.get("state_tax", 0.0) > 0


def test_ca_hoh_gets_its_own_higher_standard_deduction():
    """A CA head-of-household filer was given the SINGLE state schedule (the engine
    mapped HoH→single). CA's HoH standard deduction is the married tier ($11,080,
    double the single $5,540), so HoH filers (single parents) were over-taxed.
    AGI $90,000 HoH → state deduction $11,080, taxable $78,920.

    FAILS before the fix: state_standard_deduction is the single value (HoH fallback)."""
    draft = compute_us_return([FormExtract(form_code="W-2", jurisdiction="US", fields={"wages": 90000.0})],
                              year=2024, state="CA", user_answers={"filing_status": "hoh"})
    assert draft.line_items["state_standard_deduction"] == 11080.0
    assert draft.line_items["state_taxable_income"] == 78920.0


def test_ca_single_state_treatment_unchanged_by_hoh_fix():
    """Regression guard: single filers keep the single state schedule. The single CA
    2024 standard deduction is $5,540 (corrected from the year-lagged 2023 $5,363)."""
    draft = compute_us_return([FormExtract(form_code="W-2", jurisdiction="US", fields={"wages": 90000.0})],
                              year=2024, state="CA", user_answers={"filing_status": "single"})
    assert draft.line_items["state_standard_deduction"] == 5540.0
    assert draft.line_items["state_taxable_income"] == 84460.0


def test_ca_2024_standard_deduction_is_current_year_value():
    """The CA 2024 standard deduction is $5,540 single (it had lagged a year at the
    2023 $5,363). AGI $90,000 → taxable $84,460 (not $84,637).

    FAILS before the fix: state_standard_deduction is $5,363."""
    draft = compute_us_return([FormExtract(form_code="W-2", jurisdiction="US", fields={"wages": 90000.0})],
                              year=2024, state="CA", user_answers={"filing_status": "single"})
    assert draft.line_items["state_standard_deduction"] == 5540.0
    assert draft.line_items["state_taxable_income"] == 84460.0


def test_ny_hoh_gets_its_own_standard_deduction():
    """NY's standard deduction has a distinct head-of-household tier ($11,200,
    statutory/fixed) — but the NY table only had single ($8,000) + MFJ, so HoH
    filers fell back to the single $8,000 and were over-taxed. AGI $90,000 HoH →
    NY deduction $11,200, taxable $78,800 (was $8,000 / $82,000).

    FAILS before the fix: state_standard_deduction is $8,000 (single fallback)."""
    draft = compute_us_return([FormExtract(form_code="W-2", jurisdiction="US", fields={"wages": 90000.0})],
                              year=2024, state="NY", user_answers={"filing_status": "hoh"})
    assert draft.line_items["state_standard_deduction"] == 11200.0
    assert draft.line_items["state_taxable_income"] == 78800.0


def test_ny_single_state_treatment_unchanged():
    """Regression guard: NY single filers keep the $8,000 single deduction."""
    draft = compute_us_return([FormExtract(form_code="W-2", jurisdiction="US", fields={"wages": 90000.0})],
                              year=2024, state="NY", user_answers={"filing_status": "single"})
    assert draft.line_items["state_standard_deduction"] == 8000.0
    assert draft.line_items["state_taxable_income"] == 82000.0


def test_ca_mental_health_surcharge_above_1m():
    """CA levies a 1% Mental Health Services Tax (R&TC §17043) on taxable income
    over $1M, separate from the 12.3%-topping brackets. Wages $2,005,540 (AGI minus
    the $5,540 CA standard deduction = $2,000,000 taxable) → 1% × ($2,000,000 −
    $1,000,000) = $10,000 surcharge on top of $227,394.76 of bracket tax."""
    draft = compute_us_return([FormExtract(form_code="W-2", jurisdiction="US", fields={"wages": 2005540.0})],
                              year=2024, state="CA", user_answers={"filing_status": "single"})
    assert draft.line_items["state_mental_health_surcharge"] == 10000.0
    assert draft.line_items["state_tax"] == 237394.76


def test_ca_mental_health_surcharge_zero_below_1m():
    """Guard: taxable income below $1M → $0 surcharge (state tax unchanged)."""
    draft = compute_us_return([FormExtract(form_code="W-2", jurisdiction="US", fields={"wages": 505540.0})],
                              year=2024, state="CA", user_answers={"filing_status": "single"})
    assert draft.line_items["state_mental_health_surcharge"] == 0.0
    assert draft.line_items["state_tax"] == 45107.9
