"""US §199A 20% QBI deduction on 1099-DIV box 5 REIT dividends.

Box 5 (section 199A dividends — REIT/qualified-PTP) qualifies for the 20% §199A
deduction, with NO W-2/UBIA wage limit. The engine's QBI base read only business
income, so a filer whose only pass-through income was REIT dividends (very common —
any REIT fund/ETF holder) got $0 deduction. REIT dividends are non-qualified, so they
stay in the income-limit base.
"""
from wealthtax_agent.engines.us_engine import compute_us_return
from wealthtax_agent.state import FormExtract


def _w2(wages):
    return FormExtract(form_code="W-2", jurisdiction="US", fields={"wages": wages})


def _div(ordinary, reit=0.0, qualified=0.0):
    f = {"ordinary_dividends": ordinary}
    if reit:
        f["section_199A_dividends"] = reit
    if qualified:
        f["qualified_dividends"] = qualified
    return FormExtract(form_code="1099-DIV", jurisdiction="US", fields=f)


def _sch_c(profit):
    return FormExtract(form_code="SCH-C", jurisdiction="US", fields={"net_profit": profit})


def _single(*extracts):
    return compute_us_return(list(extracts), year=2024,
                             user_answers={"filing_status": "single", "num_dependents": "0"})


def test_reit_only_gets_20pct_qbi_deduction():
    d = _single(_w2(80000.0), _div(10000.0, reit=10000.0))
    assert d.line_items["section_199a_reit_dividends"] == 10000.0
    assert d.line_items["qbi_deduction"] == 2000.0  # 20% of 10,000


def test_no_reit_no_business_zero_qbi():
    d = _single(_w2(80000.0), _div(10000.0))
    assert d.line_items["qbi_deduction"] == 0.0


def test_reit_plus_business_combined_base():
    # $30k Sch C + $10k REIT, income limit doesn't bind. The Sch C (SE) component
    # is net of the deductible 1/2 SE tax ($2,119.43) per §1.199A-3(b)(1)(vi):
    # base = (30,000 - 2,119.43) + 10,000 = 37,880.57; x 20% = $7,576.11. The REIT
    # component is not SE income, so it is not reduced.
    d = _single(_w2(80000.0), _sch_c(30000.0), _div(10000.0, reit=10000.0))
    assert d.line_items["qbi_deduction"] == 7576.11


def test_income_limit_caps_combined_deduction():
    # Tiny taxable income caps the deduction at 20% of (taxable − net cap gain).
    # $5k REIT but very low other income → cap binds below 20% of REIT.
    d = _single(_w2(10000.0), _div(5000.0, reit=5000.0))
    # taxable income ≈ 10,000 + 5,000 − 14,600 std = 400 → cap 20% × 400 = 80.
    assert d.line_items["qbi_deduction"] == 80.0


def test_reit_deduction_reduces_tax():
    base = _single(_w2(80000.0), _div(10000.0))
    with_reit = _single(_w2(80000.0), _div(10000.0, reit=10000.0))
    assert with_reit.estimated_tax < base.estimated_tax
