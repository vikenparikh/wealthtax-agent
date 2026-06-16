"""Form 2441 Child & Dependent Care Credit (non-refundable, fixed-statutory §21).

Expense caps $3,000 (1 person) / $6,000 (2+), reduced by W-2 box 10 employer
dependent-care benefits, limited to the lesser earned income (both spouses for MFJ),
rate 35% declining 1 point per $2,000 of AGI over $15,000 to a 20% floor over $43,000.
"""
from wealthtax_agent.engines.us_engine import compute_us_return
from wealthtax_agent.state import FormExtract


def _w2(wages, dcb=0.0):
    f = {"wages": wages}
    if dcb:
        f["dependent_care_benefits"] = dcb
    return FormExtract(form_code="W-2", jurisdiction="US", fields=f)


def _credit(wage, care, persons, dcb=0.0, status="single", spouse=None, year=2024):
    ua = {"filing_status": status, "num_dependents": "0",
          "dependent_care_expenses": str(care), "num_dependent_care_persons": str(persons)}
    if spouse is not None:
        ua["spouse_earned_income"] = str(spouse)
    return compute_us_return([_w2(wage, dcb)], year=year, user_answers=ua).line_items["dependent_care_credit"]


def test_low_income_one_child_35pct():
    # $4k care, 1 person, AGI $14k → cap $3k, 35% → $1,050.
    assert _credit(14000, 4000, 1) == 1050.0


def test_agi_band_phasedown():
    # AGI $30k → 8 steps over $15k floor → 35%−8% = 27% → 3,000 × 0.27 = $810.
    assert _credit(30000, 3500, 1) == 810.0


def test_rate_boundary_15000_is_35pct():
    assert _credit(15000, 3000, 1) == 1050.0     # AGI == floor → no step
    assert _credit(15001, 3000, 1) == 1020.0     # one step → 34%


def test_rate_floor_20pct_above_43000():
    assert _credit(45000, 3000, 1) == 600.0      # 20% floor → 3,000 × 0.20


def test_box10_dcb_reduces_eligible_expense_mfj():
    # 2 persons cap $6k, $5k DCB → eligible $1k; AGI > $43k → 20% → $200.
    assert _credit(60000, 9000, 2, dcb=5000.0, status="married_filing_jointly", spouse=40000) == 200.0


def test_two_plus_persons_capped_at_6000():
    # 3 persons still caps at $6,000; AGI $14k → 35% → $2,100.
    assert _credit(14000, 8000, 3) == 2100.0


def test_mfj_spouse_no_earned_income_zero():
    # MFJ: the credit requires both spouses to have earned income.
    assert _credit(60000, 6000, 2, status="married_filing_jointly") == 0.0


def test_no_care_expense_zero():
    d = compute_us_return([_w2(50000)], year=2024,
                          user_answers={"filing_status": "single", "num_dependents": "0"})
    assert d.line_items["dependent_care_credit"] == 0.0


def test_non_refundable_capped_at_tax():
    # $14k wages, single → $0 taxable income → $0 tax; the $1,050 credit is computed
    # but cannot reduce tax below $0 (non-refundable) — federal tax stays $0.
    d = compute_us_return(
        [_w2(14000)], year=2024,
        user_answers={"filing_status": "single", "num_dependents": "0",
                      "dependent_care_expenses": "4000", "num_dependent_care_persons": "1"},
    )
    assert d.line_items["dependent_care_credit"] == 1050.0
    assert d.line_items["federal_tax"] == 0.0  # non-refundable: no refund created


def test_credit_reduces_tax_when_liability_exists():
    base = compute_us_return([_w2(60000)], year=2024,
                             user_answers={"filing_status": "single", "num_dependents": "0"})
    with_c = compute_us_return(
        [_w2(60000)], year=2024,
        user_answers={"filing_status": "single", "num_dependents": "0",
                      "dependent_care_expenses": "6000", "num_dependent_care_persons": "2"},
    )
    assert with_c.line_items["federal_tax"] < base.line_items["federal_tax"]


def test_2025_tables_same_fixed_values():
    assert _credit(14000, 4000, 1, year=2025) == 1050.0
