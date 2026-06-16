"""US self-employed health insurance deduction (§162(l), Schedule 1 line 17).

Premiums for the self-employed taxpayer/spouse/dependents are deductible above the
line, capped at the net SE earnings (net profit less the deductible half of SE tax).
Not available where the taxpayer was eligible for an employer plan (filer's
responsibility, not modelled).
"""
from wealthtax_agent.engines.us_engine import compute_us_return
from wealthtax_agent.state import FormExtract


def _nec(amount):
    return FormExtract(form_code="1099-NEC", jurisdiction="US", fields={"nonemployee_compensation": amount})


def _draft(se_income, premium):
    return compute_us_return([_nec(se_income)], year=2024,
                             user_answers={"filing_status": "single", "num_dependents": "0",
                                           "self_employed_health_insurance": str(premium)})


def test_premium_below_se_limit_fully_deductible():
    d = _draft(50000, 8000)
    assert d.line_items["self_employed_health_insurance_deduction"] == 8000.0


def test_premium_capped_at_se_net_earnings():
    # Premium $12k but SE net (income − SE-tax deduction) is the limit.
    d = _draft(10000, 12000)
    expected = round(10000 - d.line_items["se_tax_deduction"], 2)
    assert d.line_items["self_employed_health_insurance_deduction"] == expected
    assert d.line_items["self_employed_health_insurance_deduction"] < 10000


def test_no_se_income_no_deduction():
    # Wages-only filer (no SE income) → limit $0 → no deduction even with premiums.
    d = compute_us_return([FormExtract(form_code="W-2", jurisdiction="US", fields={"wages": 60000.0})],
                          year=2024, user_answers={"filing_status": "single", "num_dependents": "0",
                                                   "self_employed_health_insurance": "8000"})
    assert d.line_items["self_employed_health_insurance_deduction"] == 0.0


def test_deduction_reduces_agi():
    base = _draft(50000, 0)
    with_d = _draft(50000, 8000)
    assert round(base.line_items["agi"] - with_d.line_items["agi"], 2) == 8000.0


def test_no_premium_zero():
    d = compute_us_return([_nec(50000)], year=2024,
                          user_answers={"filing_status": "single", "num_dependents": "0"})
    assert d.line_items["self_employed_health_insurance_deduction"] == 0.0
