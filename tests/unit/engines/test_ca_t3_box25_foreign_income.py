"""T3 box 25 (foreign non-business income) must be included in CA total income.

The T3 extractor captures box 25 (foreign_non_business_income) — foreign interest/
dividends flowed through a Canadian trust/fund, common on diversified ETFs — but the
engine never read it, so it was dropped from total income and the filer was
under-taxed. It is fully taxable other income (T1 line 12100), distinct from box 26.
"""
from wealthtax_agent.engines.ca_engine import compute_ca_return
from wealthtax_agent.state import FormExtract


def _t4(wages=60000.0):
    return FormExtract(form_code="T4", jurisdiction="CA", fields={"employment_income": wages})


def _t3(**fields):
    return FormExtract(form_code="T3", jurisdiction="CA", fields=fields)


def test_box25_foreign_income_in_total_income():
    extracts = [_t4(), _t3(foreign_non_business_income=4000.0)]
    d = compute_ca_return(extracts, year=2024, province="ON")
    assert d.line_items["trust_foreign_non_business_income"] == 4000.0
    # total_income reflects the $4,000 on top of the $60k salary.
    base = compute_ca_return([_t4()], year=2024, province="ON")
    assert round(d.total_income - base.total_income, 2) == 4000.0


def test_box25_and_box26_both_counted_no_double_count():
    # Box 25 (foreign) and box 26 (other_income) are distinct boxes — both included,
    # neither swallowing the other.
    extracts = [_t4(), _t3(foreign_non_business_income=3000.0, other_income=2000.0)]
    d = compute_ca_return(extracts, year=2024, province="ON")
    base = compute_ca_return([_t4()], year=2024, province="ON")
    assert d.line_items["trust_foreign_non_business_income"] == 3000.0
    assert round(d.total_income - base.total_income, 2) == 5000.0  # 3000 + 2000


def test_box25_increases_tax():
    no_foreign = compute_ca_return([_t4()], year=2024, province="ON")
    with_foreign = compute_ca_return([_t4(), _t3(foreign_non_business_income=4000.0)],
                                     year=2024, province="ON")
    assert with_foreign.estimated_tax > no_foreign.estimated_tax


def test_no_t3_no_regression():
    d = compute_ca_return([_t4()], year=2024, province="ON")
    assert d.line_items["trust_foreign_non_business_income"] == 0.0
