"""US Foreign Tax Credit (Form 1116, IRC §901 / §904 limitation).

A US filer taxed by another country on foreign-source income may credit that
foreign income tax against US tax, limited by §904 to the US tax attributable to
the foreign-source income:

    FTC = min(foreign_tax_paid,
              US_tax_before_credits x foreign_source_income / total_taxable_income)

This is THE anti-double-taxation mechanism for the app's CA/US/IN cross-border
users. Previously the engine only emitted advisory notes and credited $0, so the
filer was fully double-taxed. v1 is single-basket, current-year, no carryforward.
"""
from wealthtax_agent.engines.us_engine import compute_us_return
from wealthtax_agent.state import FormExtract


def _w2(wages: float = 120000.0):
    return [FormExtract(form_code="W-2", jurisdiction="US", fields={"wages": wages})]


def test_foreign_tax_below_904_limit_credited_in_full():
    base = compute_us_return(_w2(), 2024, user_answers={})
    d = compute_us_return(_w2(), 2024, user_answers={
        "foreign_source_income": "30000", "foreign_tax_paid": "2000"})
    # $2,000 foreign tax is well under the §904 limit -> credited in full.
    assert d.line_items["foreign_tax_credit"] == 2000.0
    # US tax drops by exactly the credit (non-refundable, tax exceeds it).
    assert round(base.line_items["federal_tax"] - d.line_items["federal_tax"], 2) == 2000.0


def test_foreign_tax_above_904_limit_is_capped():
    # $120k wages, $30k foreign-source, $9k foreign tax paid.
    # taxable_income 105,400; tax_before_credits 18,338.50.
    # limit = 18,338.50 x 30,000/105,400 = 5,219.69; FTC = min(9000, 5219.69).
    d = compute_us_return(_w2(), 2024, user_answers={
        "foreign_source_income": "30000", "foreign_tax_paid": "9000"})
    assert d.line_items["foreign_tax_credit"] == 5219.69
    # The disallowed excess ($3,780.31) is NOT credited (no carryforward in v1).


def test_no_foreign_income_no_credit():
    d = compute_us_return(_w2(), 2024, user_answers={"foreign_tax_paid": "5000"})
    # Zero foreign-source income -> §904 ratio is 0 -> no credit.
    assert d.line_items.get("foreign_tax_credit", 0.0) == 0.0


def test_ftc_does_not_create_refund():
    # Tiny tax, large foreign tax: FTC cannot push federal_tax below 0 or refund.
    d = compute_us_return(_w2(15000.0), 2024, user_answers={
        "foreign_source_income": "10000", "foreign_tax_paid": "9000"})
    assert d.line_items["federal_tax"] == 0.0


def test_non_numeric_foreign_inputs_tolerated():
    # Guards the coercion-crash vein (#143): worded inputs must not raise.
    d = compute_us_return(_w2(), 2024, user_answers={
        "foreign_source_income": "lots", "foreign_tax_paid": "some"})
    assert d.line_items.get("foreign_tax_credit", 0.0) == 0.0


def _foreign_heavy():
    # 60k foreign wages + a US capital loss -> total taxable income falls BELOW
    # the foreign-source component, so the naive §904 ratio exceeds 1.0.
    return [
        FormExtract(form_code="W-2", jurisdiction="US", fields={"wages": 60000.0}),
        FormExtract(form_code="SCH-D", jurisdiction="US", fields={"net_long_term_capital_gain": -3000.0}),
    ]


def test_section_904_limit_never_exceeds_total_us_tax():
    # §904 ratio (foreign / total taxable) cannot exceed 1.0: the foreign component
    # is a subset of total taxable income, so the limit caps at the full US tax.
    ext = _foreign_heavy()
    pre_credit_tax = compute_us_return(ext, 2024, user_answers={}).line_items["federal_tax"]  # 4856, no other credits
    d = compute_us_return(ext, 2024, user_answers={
        "foreign_source_income": "50000", "foreign_tax_paid": "9000"})
    # FTC must not exceed the total US tax (was $5,726.42 before the clamp).
    assert d.line_items["foreign_tax_credit"] == pre_credit_tax
    assert d.line_items["foreign_tax_credit"] <= pre_credit_tax
    assert d.line_items["federal_tax"] == 0.0


def test_section_904_carryforward_note_uses_clamped_excess():
    ext = _foreign_heavy()
    pre_credit_tax = compute_us_return(ext, 2024, user_answers={}).line_items["federal_tax"]
    d = compute_us_return(ext, 2024, user_answers={
        "foreign_source_income": "50000", "foreign_tax_paid": "9000"})
    # The disallowed (carryforward) excess is foreign_tax - clamped_limit = 9000 - 4856.
    expected_excess = round(9000.0 - pre_credit_tax, 2)
    assert any(f"${expected_excess:,.2f} of foreign tax exceeds" in n for n in d.notes)
