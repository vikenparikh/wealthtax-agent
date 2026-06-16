"""Tests for the quarterly estimated-tax voucher logic (filing/quarterly.py).

Pure money logic that was untested: the US 1040-ES and CA instalment
threshold gates, the per-quarter sizing, the due-date schedules (including
the US Q4 rolling into January of the next year), and the DRAFT/not-
transmitted safety marker on every voucher.
"""

from wealthtax_agent.filing.quarterly import (
    quarterly_ca_instalments,
    quarterly_us_1040es,
)
from wealthtax_agent.state import DraftReturn


def _draft(jurisdiction, totals=None, line_items=None):
    return DraftReturn(jurisdiction=jurisdiction, totals=totals or {}, line_items=line_items or {})


# --- US 1040-ES --------------------------------------------------------------


def test_us_no_voucher_below_thresholds():
    d = _draft("US", totals={"total_tax": 800.0},
               line_items={"tax_withheld": 0.0, "self_employment_tax": 0.0})
    assert quarterly_us_1040es(d, 2025) == {}


def test_us_no_voucher_when_withholding_covers_tax():
    d = _draft("US", totals={"total_tax": 9000.0},
               line_items={"tax_withheld": 9000.0, "self_employment_tax": 0.0})
    assert quarterly_us_1040es(d, 2025) == {}


def test_us_voucher_sized_at_a_quarter_of_amount_owed():
    d = _draft("US", totals={"total_tax": 9000.0, "balance_owing": 7000.0},
               line_items={"tax_withheld": 2000.0})
    v = quarterly_us_1040es(d, 2025)
    assert set(v) == {"Q1", "Q2", "Q3", "Q4"}
    assert "Estimated payment: $1,750.00" in v["Q1"]  # balance_owing 7000 / 4
    assert "DRAFT — not transmitted" in v["Q1"]


def test_us_voucher_nets_refundable_credits_via_balance_owing():
    """The voucher must size on the net amount owed (balance_owing), which the
    engine computes after withholding AND refundable credits/extra payments — not
    total_tax − withholding, which ignores EITC/ACTC and over-states the payment.
    total_tax $10,000, withholding $2,000, $4,000 of refundable credits →
    balance_owing $4,000 → $1,000/qtr, not $2,000/qtr.

    FAILS before the fix: sizes on (10,000 − 2,000)/4 = $2,000."""
    d = _draft("US", totals={"total_tax": 10000.0, "balance_owing": 4000.0},
               line_items={"tax_withheld": 2000.0, "self_employment_tax": 6000.0})
    v = quarterly_us_1040es(d, 2025)
    assert "Estimated payment: $1,000.00" in v["Q1"]


def test_us_due_dates_roll_q4_into_next_january():
    d = _draft("US", totals={"total_tax": 9000.0, "balance_owing": 7000.0},
               line_items={"tax_withheld": 2000.0})
    v = quarterly_us_1040es(d, 2025)
    assert "2025-04-15" in v["Q1"]
    assert "2025-06-15" in v["Q2"]
    assert "2025-09-15" in v["Q3"]
    assert "2026-01-15" in v["Q4"]


def test_us_high_se_tax_triggers_voucher_even_when_income_tax_is_withheld():
    d = _draft("US", totals={"total_tax": 500.0},
               line_items={"tax_withheld": 500.0, "self_employment_tax": 5000.0})
    v = quarterly_us_1040es(d, 2025)
    assert v  # se_tax > 1000 keeps it non-empty even though amount owed is 0
    assert "$0.00" in v["Q1"]
    assert "Self-employment tax (informational): $5,000.00" in v["Q1"]


# --- CA instalments ----------------------------------------------------------


def test_ca_no_instalment_below_thresholds():
    d = _draft("CA", totals={"balance_owing": 1000.0}, line_items={"net_business_income": 0.0})
    assert quarterly_ca_instalments(d, 2025) == {}


def test_ca_instalment_sized_from_balance_owing():
    d = _draft("CA", totals={"balance_owing": 8000.0})
    v = quarterly_ca_instalments(d, 2025)
    assert set(v) == {"Q1", "Q2", "Q3", "Q4"}
    assert "$2,000.00" in v["Q1"]  # 8000 / 4
    assert "DRAFT — not transmitted" in v["Q1"]


def test_ca_instalment_falls_back_to_self_employment_when_no_balance():
    d = _draft("CA", totals={"balance_owing": 0.0}, line_items={"net_business_income": 40000.0})
    v = quarterly_ca_instalments(d, 2025)
    assert v  # self_emp > 5000
    assert "$2,500.00" in v["Q1"]  # 40000 * 0.25 / 4


def test_ca_due_dates_are_quarter_end_15ths():
    d = _draft("CA", totals={"balance_owing": 8000.0})
    v = quarterly_ca_instalments(d, 2025)
    assert "2025-03-15" in v["Q1"]
    assert "2025-06-15" in v["Q2"]
    assert "2025-09-15" in v["Q3"]
    assert "2025-12-15" in v["Q4"]
