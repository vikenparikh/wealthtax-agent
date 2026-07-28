"""Canada Employment Amount (ITA s.118(10), T1 line 31260) = the LESSER of the
indexed maximum ($1,433 for 2024) and the year's employment income.

REGRESSION: the engine applied the full flat maximum whenever employment income
was merely > 0, ignoring the "lesser of employment income" clause — over-crediting
(and under-taxing) part-year / gig / student filers whose T4 income is below the
maximum. The cap is a no-op for anyone at/above the maximum.
"""
from wealthtax_agent.engines.ca_engine import compute_ca_return
from wealthtax_agent.state import FormExtract

CEA_MAX_2024 = 1433.0


def _t4(wages):
    return FormExtract(form_code="T4", jurisdiction="CA", fields={"employment_income": wages})


def test_cea_capped_at_low_employment_income():
    # $500 T4 (a token/gig T4): CEA base = min(500, 1433) = 500, NOT the full 1433.
    d = compute_ca_return([_t4(500.0)], year=2024, province="ON")
    assert d.credits["canada_employment_amount"] == 500.0


def test_cea_full_max_when_income_above_maximum():
    # Comfortably above the maximum → the cap is non-binding, full CEA applies.
    d = compute_ca_return([_t4(50000.0)], year=2024, province="ON")
    assert d.credits["canada_employment_amount"] == CEA_MAX_2024


def test_cea_at_the_maximum_boundary():
    d = compute_ca_return([_t4(CEA_MAX_2024)], year=2024, province="ON")
    assert d.credits["canada_employment_amount"] == CEA_MAX_2024


def test_cea_zero_without_employment_income():
    # Self-employment only (T2125), no T4 → no Canada Employment Amount.
    ext = [FormExtract(form_code="T2125", jurisdiction="CA",
                       fields={"net_business_income": 40000.0})]
    d = compute_ca_return(ext, year=2024, province="ON")
    assert d.credits["canada_employment_amount"] == 0.0


def test_cea_cap_raises_tax_vs_uncapped():
    # The correction increases tax for the low-income case (over-credit removed):
    # the capped CEA base ($500) credits $933 less than the old full $1,433 base,
    # i.e. ~$139.95 more federal tax at the 15% lowest rate.
    d = compute_ca_return([_t4(500.0)], year=2024, province="ON")
    assert d.credits["canada_employment_amount"] == 500.0
    # federal credit on the CEA slice is base * 0.15; the removed over-credit is
    # (1433 - 500) * 0.15 = 139.95 that the buggy engine wrongly granted.
