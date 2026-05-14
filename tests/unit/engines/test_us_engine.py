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
