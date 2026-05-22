"""Quarterly estimated-tax safe-harbour calculator (US §6654).

Given YTD P&L, W-2 withholding, and last-year tax liability, computes the
minimum Q1–Q4 payments to avoid underpayment penalties.

Safe-harbour rules used
-----------------------
  Option A (100% of prior-year): pay 100% of last year's tax (110% if
  prior-year AGI > $150 000) in equal quarterly instalments.

  Option B (90% of current year): pay 90% of the current-year estimated
  tax. We use this when it produces a lower payment than Option A.

Both options are returned; the caller should take the lower of the two for
each quarter.

CRA (Canada) instalments follow a parallel calculation — see
``quarterly_ca_instalments`` in ``filing/quarterly.py`` for the simpler
no-safe-harbour version; this module focuses on the US side where
QQQ day-trading generates significant quarterly SE/short-term-gain income.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional


_SE_TAX_RATE = 0.1530         # 15.3% self-employment tax (SS + Medicare)
_SE_DEDUCTIBLE_HALF = 0.5000  # half of SE tax is deductible from AGI
_LTCG_RATES = {0: 0.0, 44625: 0.15, 492300: 0.20}   # 2024 thresholds (single)
_ORDINARY_BRACKETS_SINGLE_2024 = [
    (11600, 0.10),
    (47150, 0.12),
    (100525, 0.22),
    (191950, 0.24),
    (243725, 0.32),
    (609350, 0.35),
    (float("inf"), 0.37),
]
_STANDARD_DEDUCTION_SINGLE_2024 = 14600.0

# IRS due dates (year = tax year, e.g. 2025)
_US_DUE_DATES = [
    ("Q1", 4, 15),   # April 15
    ("Q2", 6, 15),   # June 15
    ("Q3", 9, 15),   # September 15
    ("Q4", 1, 15),   # January 15 next year (+1)
]


@dataclass
class EstimatedTaxResult:
    tax_year: int
    estimated_annual_tax: float        # best estimate of full-year liability
    prior_year_tax: float
    withholding_ytd: float
    safe_harbour_a: float              # 100/110% of prior-year tax (annual total)
    safe_harbour_b: float              # 90% of current-year estimate (annual total)
    recommended_annual: float          # min(a, b)
    quarterly_payments: Dict[str, float]  # {"Q1": …, "Q2": …, …}
    quarterly_due_dates: Dict[str, str]
    note: str = ""


def _progressive_tax(income: float, brackets: list) -> float:
    """Compute tax under a progressive bracket table."""
    tax = 0.0
    prev = 0.0
    for threshold, rate in brackets:
        if income <= prev:
            break
        taxable = min(income, threshold) - prev
        tax += taxable * rate
        prev = threshold
    return tax


def _estimate_federal_tax(
    w2_wages: float,
    se_net_profit: float,
    short_term_gains: float,
    long_term_gains: float,
    other_ordinary: float,
    filing_status: str = "single",
    tax_year: int = 2025,
) -> float:
    """Rough federal income + SE tax estimate."""
    se_tax = se_net_profit * _SE_TAX_RATE
    se_deduction = se_tax * _SE_DEDUCTIBLE_HALF

    agi = w2_wages + se_net_profit + short_term_gains + long_term_gains + other_ordinary - se_deduction
    std_ded = _STANDARD_DEDUCTION_SINGLE_2024  # simplified: single only for now
    ordinary_income = max(0.0, agi - long_term_gains - std_ded)

    # Ordinary tax on (wages + STG + SE net + other - deductions)
    ordinary_tax = _progressive_tax(ordinary_income, _ORDINARY_BRACKETS_SINGLE_2024)

    # Preferential LTCG rate on top of ordinary stack
    ltcg_rate = 0.15
    for threshold, rate in sorted(_LTCG_RATES.items()):
        if ordinary_income >= threshold:
            ltcg_rate = rate
    ltcg_tax = max(0.0, long_term_gains) * ltcg_rate

    total_tax = ordinary_tax + ltcg_tax + se_tax
    return round(total_tax, 2)


def compute_estimated_payments(
    tax_year: int,
    w2_wages: float = 0.0,
    se_net_profit: float = 0.0,
    short_term_gains: float = 0.0,
    long_term_gains: float = 0.0,
    other_ordinary: float = 0.0,
    withholding_ytd: float = 0.0,
    prior_year_tax: float = 0.0,
    prior_year_agi: float = 0.0,
    filing_status: str = "single",
) -> EstimatedTaxResult:
    """Compute quarterly safe-harbour estimated tax payments.

    Parameters mirror what a tax professional would gather from W-2 box 1,
    1099-B/DIV/INT, and Schedule C.

    Returns
    -------
    EstimatedTaxResult with quarterly payment schedule.
    """
    estimated_annual = _estimate_federal_tax(
        w2_wages=w2_wages,
        se_net_profit=se_net_profit,
        short_term_gains=short_term_gains,
        long_term_gains=long_term_gains,
        other_ordinary=other_ordinary,
        filing_status=filing_status,
        tax_year=tax_year,
    )

    # Safe harbour A: 100% of prior-year (110% if prior AGI > $150 000, §6654(d)(1)(B)(ii))
    # IRS rule is strictly > $150,000 (not >= ); taxpayers at exactly $150,000 use 100%.
    multiplier_a = 1.10 if prior_year_agi > 150_000 else 1.00
    safe_a = prior_year_tax * multiplier_a

    # Safe harbour B: 90% of current-year estimate
    safe_b = estimated_annual * 0.90

    recommended = min(safe_a, safe_b)

    # Net amount after withholding
    net_needed = max(0.0, recommended - withholding_ytd)
    per_quarter = round(net_needed / 4.0, 2)

    payments: Dict[str, float] = {}
    due_dates: Dict[str, str] = {}
    for label, month, day in _US_DUE_DATES:
        yr = tax_year if month != 1 else tax_year + 1
        due_dates[label] = date(yr, month, day).isoformat()
        payments[label] = per_quarter

    note = (
        f"Safe harbour A (prior-year method): ${safe_a:,.2f}/yr — "
        f"{'110%' if multiplier_a == 1.10 else '100%'} of ${prior_year_tax:,.2f}. "
        f"Safe harbour B (90% current): ${safe_b:,.2f}/yr. "
        f"Recommending ${recommended:,.2f}/yr (${per_quarter:,.2f}/quarter) "
        f"after ${withholding_ytd:,.2f} withholding. "
        "DRAFT — consult a licensed CPA before paying."
    )

    return EstimatedTaxResult(
        tax_year=tax_year,
        estimated_annual_tax=estimated_annual,
        prior_year_tax=prior_year_tax,
        withholding_ytd=withholding_ytd,
        safe_harbour_a=safe_a,
        safe_harbour_b=safe_b,
        recommended_annual=recommended,
        quarterly_payments=payments,
        quarterly_due_dates=due_dates,
        note=note,
    )
