"""Property: total tax is MONOTONE NON-DECREASING in income.

A well-formed tax system never lets earning $1 more REDUCE your total tax —
marginal-relief/cliff mechanics cap the marginal rate at (at most) ~100%, never
make it negative. Violations are real bugs: e.g. the India surcharge
marginal-relief defect (#231) made a resident just above ₹1cr pay ~₹2.8L LESS
tax by earning ₹1,000 more. This sweeps each jurisdiction's engine across income
— densely around the known cliff thresholds where such bugs hide — and asserts
`total_tax(hi) >= total_tax(lo)` (within a $1 rounding tolerance). It guards the
whole class across US / India / Canada, not just the one point each fix pinned.
"""
import pytest

from wealthtax_agent.engines.ca_engine import compute_ca_return
from wealthtax_agent.engines.in_engine import compute_in_return
from wealthtax_agent.engines.us_engine import compute_us_return
from wealthtax_agent.state import FormExtract

_TOL = 1.0  # allow ±$1 of pure-rounding wobble; real bugs are orders larger


def _grid(max_income: float, thresholds, n_coarse: int = 180):
    """Sorted income points: a coarse linear sweep + dense clusters straddling
    each cliff threshold (where marginal-relief/phase-out bugs live)."""
    pts = set()
    step = max_income / n_coarse
    x = 0.0
    while x <= max_income:
        pts.add(round(x, 2))
        x += step
    for t in thresholds:
        for d in (-10000, -5000, -1000, -100, -1, 0, 1, 100, 1000, 5000, 10000):
            v = t + d
            if 0 <= v <= max_income:
                pts.add(round(float(v), 2))
    return sorted(pts)


def _assert_monotone(fn, grid, label):
    prev_income, prev_tax = None, None
    for inc in grid:
        tax = fn(inc)
        if prev_tax is not None:
            assert tax >= prev_tax - _TOL, (
                f"{label}: total_tax DROPPED from {prev_tax:.2f} at income "
                f"{prev_income:,.0f} to {tax:.2f} at {inc:,.0f} "
                f"(Δincome={inc - prev_income:,.0f}, Δtax={tax - prev_tax:,.2f}) "
                f"— negative marginal rate / non-monotone tax (a #231-class bug)"
            )
        prev_income, prev_tax = inc, tax


# --- US federal (single, W-2 wages) -----------------------------------------
def _us_tax(wages):
    d = compute_us_return(
        [FormExtract(form_code="W-2", jurisdiction="US", fields={"wages": wages})],
        year=2024, user_answers={"filing_status": "single"},
    )
    return d.estimated_tax


def test_us_total_tax_monotone_in_wages():
    # brackets, standard deduction, NIIT ($200k), additional-medicare ($200k)
    grid = _grid(2_000_000, [14_600, 47_025, 100_525, 191_950, 200_000, 250_000, 609_350])
    _assert_monotone(_us_tax, grid, "US single wages")


# --- India (Form-16 gross salary) — both regimes ----------------------------
def _in_tax(gross, regime):
    d = compute_in_return(
        [FormExtract(form_code="FORM-16", jurisdiction="IN", fields={"gross_salary": gross})],
        year=2024, regime=regime, residency_status="ROR", user_answers={"age": "30"},
    )
    return d.estimated_tax


@pytest.mark.parametrize("regime", ["old", "new"])
def test_in_total_tax_monotone_in_income(regime):
    # slab edges + the 87A rebate edge + surcharge tiers 50L/1cr/2cr/5cr
    grid = _grid(
        6_00_00_000,
        [2_50_000, 5_00_000, 7_00_000, 10_00_000, 50_00_000, 1_00_00_000, 2_00_00_000, 5_00_00_000],
    )
    _assert_monotone(lambda inc: _in_tax(inc, regime), grid, f"India {regime}")


# --- Canada (T4 employment income, ON) --------------------------------------
def _ca_tax(income):
    d = compute_ca_return(
        [FormExtract(form_code="T4", jurisdiction="CA", fields={"employment_income": income})],
        year=2024, province="ON",
    )
    return d.estimated_tax


def test_ca_total_tax_monotone_in_income():
    # federal + ON brackets, BPA high-income grind (173,205/246,752), ON surtax
    grid = _grid(1_000_000, [55_867, 111_733, 173_205, 246_752, 111_733, 173_229])
    _assert_monotone(_ca_tax, grid, "Canada ON employment")
