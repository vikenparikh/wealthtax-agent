"""NY Head-of-Household state tax brackets.

The NY state tables defined head_of_household only under standard_deduction, never
under brackets_by_status — so the engine (us_engine.py:887) fell back to the SINGLE
bracket schedule for HoH filers. NY's HoH rungs are statutorily wider than single, so
HoH filers (commonly single parents) were over-taxed at the state level. NY brackets
are fixed 2021-2027, so 2023/2024/2025 are identical.
"""
import pytest

from wealthtax_agent.engines.us_engine import compute_us_return
from wealthtax_agent.state import FormExtract


def _ny(wages, status, year=2024):
    return compute_us_return(
        [FormExtract(form_code="W-2", jurisdiction="US", fields={"wages": wages})],
        year=year, state="NY", user_answers={"filing_status": status},
    )


def test_ny_hoh_uses_hoh_brackets_not_single():
    # HoH $90k 2024 → taxable 78,800 (after $11,200 HoH std). HoH-bracket tax is
    # $4,085.38; the single schedule on the same taxable income gives $4,169.00.
    d = _ny(90000.0, "hoh")
    assert d.line_items["state_taxable_income"] == 78800.0
    assert d.line_items["state_tax"] == 4085.38


def test_ny_hoh_taxed_less_than_single_same_taxable_income():
    # Same taxable income ($78,800) for HoH vs single isolates the bracket effect:
    # HoH (wider rungs) must be taxed LESS than single. (single std 8,000 → wages
    # 86,800 yields the same 78,800 taxable.)
    hoh = _ny(90000.0, "hoh")                 # taxable 78,800
    single = _ny(86800.0, "single")           # taxable 78,800
    assert single.line_items["state_taxable_income"] == hoh.line_items["state_taxable_income"]
    assert hoh.line_items["state_tax"] < single.line_items["state_tax"]
    assert single.line_items["state_tax"] - hoh.line_items["state_tax"] == pytest.approx(83.62, abs=0.01)


def test_ny_hoh_gap_widens_at_high_income():
    # At $300k the single schedule has crossed into 6% (at $215,400) while HoH is
    # still in 5.5% (until $269,300) — the over-tax is materially larger.
    hoh = _ny(311200.0, "hoh")                # taxable 300,000
    single = _ny(308000.0, "single")          # taxable 300,000
    assert hoh.line_items["state_taxable_income"] == single.line_items["state_taxable_income"] == 300000.0
    assert single.line_items["state_tax"] - hoh.line_items["state_tax"] > 300.0


def test_ny_single_brackets_unchanged_regression():
    d = _ny(90000.0, "single")                # taxable 82,000
    assert d.line_items["state_taxable_income"] == 82000.0
    # 340 + 144 + 115.50 + 5.5%*(80,650-13,900) + 6%*(82,000-80,650)
    # = 340 + 144 + 115.50 + 3,671.25 + 81.00 = 4,351.75
    assert d.line_items["state_tax"] == 4351.75


def test_ny_hoh_brackets_fixed_across_years():
    # NY brackets are statutorily fixed 2021-2027 → identical HoH tax each year.
    assert _ny(90000.0, "hoh", 2023).line_items["state_tax"] == 4085.38
    assert _ny(90000.0, "hoh", 2024).line_items["state_tax"] == 4085.38
    assert _ny(90000.0, "hoh", 2025).line_items["state_tax"] == 4085.38
