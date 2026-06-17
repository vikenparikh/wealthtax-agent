"""Ontario Health Premium (Form ON428).

A premium on TAXABLE income, expressible as a sum of capped ramps and capped at
$900. Non-indexed since 2004. It is part of Ontario tax payable. Previously the
engine omitted it, under-charging every Ontario filer with taxable income over
$20,000. Boundary values (taxable income → OHP):
  ≤20,000 → $0 ; 25,000 → $300 ; 36,000 → $300 ; 48,000 → $450 ;
  48,600 → $600 ; 72,600 → $750 ; 200,600+ → $900 (cap).
"""
import pytest
from wealthtax_agent.engines.ca_engine import compute_ca_return
from wealthtax_agent.state import FormExtract


def _ohp(taxable_employment: float):
    d = compute_ca_return(
        [FormExtract(form_code="T4", jurisdiction="CA", fields={"employment_income": taxable_employment})],
        2024, province="ON", user_answers={})
    return d.line_items["ontario_health_premium"]


@pytest.mark.parametrize("income,expected", [
    (15000.0, 0.0),     # below the $20k floor
    (20000.0, 0.0),     # at the floor
    (25000.0, 300.0),   # first ramp tops out
    (30000.0, 300.0),   # flat
    (50000.0, 600.0),   # 300 + 150 + 150
    (120000.0, 750.0),  # 300 + 150 + 150 + 150
    (250000.0, 900.0),  # cap
])
def test_ontario_health_premium_schedule(income, expected):
    assert _ohp(income) == expected


def test_ohp_folds_into_provincial_tax():
    d = compute_ca_return(
        [FormExtract(form_code="T4", jurisdiction="CA", fields={"employment_income": 50000.0})],
        2024, province="ON", user_answers={})
    # $50k: basic+surtax provincial tax 1,898.85 (no surtax at this income) + OHP 600.
    assert d.line_items["ontario_health_premium"] == 600.0
    assert d.line_items["provincial_tax"] == round(1898.85 + 600.0, 2)


def test_no_health_premium_outside_ontario():
    d = compute_ca_return(
        [FormExtract(form_code="T4", jurisdiction="CA", fields={"employment_income": 80000.0})],
        2024, province="AB", user_answers={})
    assert d.line_items.get("ontario_health_premium", 0.0) == 0.0
