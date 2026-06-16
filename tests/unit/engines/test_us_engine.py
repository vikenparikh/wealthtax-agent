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
    AGI $90,000 HoH → state deduction $11,080, taxable $78,920 (was single's
    $5,363 / $84,637 → ~$532 of over-tax removed).

    FAILS before the fix: state_standard_deduction is $5,363 (single)."""
    draft = compute_us_return([FormExtract(form_code="W-2", jurisdiction="US", fields={"wages": 90000.0})],
                              year=2024, state="CA", user_answers={"filing_status": "hoh"})
    assert draft.line_items["state_standard_deduction"] == 11080.0
    assert draft.line_items["state_taxable_income"] == 78920.0


def test_ca_single_state_treatment_unchanged_by_hoh_fix():
    """Regression guard: single filers keep the single state schedule untouched."""
    draft = compute_us_return([FormExtract(form_code="W-2", jurisdiction="US", fields={"wages": 90000.0})],
                              year=2024, state="CA", user_answers={"filing_status": "single"})
    assert draft.line_items["state_standard_deduction"] == 5363.0
    assert draft.line_items["state_taxable_income"] == 84637.0


def test_ca_mental_health_surcharge_above_1m():
    """CA levies a 1% Mental Health Services Tax (R&TC §17043) on taxable income
    over $1M, separate from the 12.3%-topping brackets. Wages $2,005,363 (AGI minus
    the $5,363 CA standard deduction = $2,000,000 taxable) → 1% × ($2,000,000 −
    $1,000,000) = $10,000 surcharge on top of $227,394.76 of bracket tax.

    FAILS before the fix: no 'state_mental_health_surcharge' key; state_tax is
    $227,394.76 (surcharge omitted)."""
    draft = compute_us_return([FormExtract(form_code="W-2", jurisdiction="US", fields={"wages": 2005363.0})],
                              year=2024, state="CA", user_answers={"filing_status": "single"})
    assert draft.line_items["state_mental_health_surcharge"] == 10000.0
    assert draft.line_items["state_tax"] == 237394.76


def test_ca_mental_health_surcharge_zero_below_1m():
    """Guard: taxable income below $1M → $0 surcharge (state tax unchanged)."""
    draft = compute_us_return([FormExtract(form_code="W-2", jurisdiction="US", fields={"wages": 505363.0})],
                              year=2024, state="CA", user_answers={"filing_status": "single"})
    assert draft.line_items["state_mental_health_surcharge"] == 0.0
    assert draft.line_items["state_tax"] == 45107.9
