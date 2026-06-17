"""US §25E Used Clean Vehicle Credit (Form 8936).

IRC §25E (Inflation Reduction Act 2022): a buyer of a qualifying USED clean
vehicle may claim the lesser of $4,000 or 30% of the sale price — a non-
refundable credit with no carryforward. There is a hard MAGI eligibility cliff
(no phase-out band): $75,000 single / $112,500 HoH / $150,000 MFJ; above the
cliff the credit is $0. All of $4,000 / 30% / the MAGI cliffs are fixed by
statute through 2032 (non-indexed). Vehicle-eligibility details (≥2 model years
old, ≤$25k price, dealer sale, first transfer) are the filer's responsibility.
Previously the engine ignored the input.
"""
from wealthtax_agent.engines.us_engine import compute_us_return
from wealthtax_agent.state import FormExtract


def _w2(wages: float = 60000.0):
    return [FormExtract(form_code="W-2", jurisdiction="US", fields={"wages": wages})]


def test_30pct_binds_when_price_below_13333():
    base = compute_us_return(_w2(), 2024, user_answers={})
    d = compute_us_return(_w2(), 2024, user_answers={"used_clean_vehicle_price": "10000"})
    # min($4,000, 30% x $10,000 = $3,000) = $3,000.
    assert d.line_items["used_clean_vehicle_credit"] == 3000.0
    assert round(base.line_items["federal_tax"] - d.line_items["federal_tax"], 2) == 3000.0


def test_4000_cap_binds_for_higher_priced_vehicle():
    d = compute_us_return(_w2(), 2024, user_answers={"used_clean_vehicle_price": "20000"})
    # min($4,000, 30% x $20,000 = $6,000) = $4,000 (cap, not 30%).
    assert d.line_items["used_clean_vehicle_credit"] == 4000.0
    # Never exceeds $4,000 even at the $25,000 price ceiling.
    d25 = compute_us_return(_w2(), 2024, user_answers={"used_clean_vehicle_price": "25000"})
    assert d25.line_items["used_clean_vehicle_credit"] == 4000.0


def test_magi_cliff_zeroes_credit_and_is_status_keyed():
    # Single filer, $80k wages -> MAGI $80k > $75k cliff -> credit $0.
    single = compute_us_return(_w2(80000.0), 2024,
                               user_answers={"filing_status": "single", "used_clean_vehicle_price": "20000"})
    assert single.line_items["used_clean_vehicle_credit"] == 0.0
    # Same $80k income as MFJ -> under the $150k cliff -> credit restored to $4,000.
    mfj = compute_us_return(_w2(80000.0), 2024,
                            user_answers={"filing_status": "mfj", "used_clean_vehicle_price": "20000"})
    assert mfj.line_items["used_clean_vehicle_credit"] == 4000.0


def test_no_vehicle_input_no_credit():
    d = compute_us_return(_w2(), 2024, user_answers={})
    assert d.line_items.get("used_clean_vehicle_credit", 0.0) == 0.0


def test_credit_is_non_refundable():
    # Low income (tiny tax): credit cannot create a refund beyond zeroing tax.
    d = compute_us_return(_w2(15000.0), 2024, user_answers={"used_clean_vehicle_price": "20000"})
    assert d.line_items["federal_tax"] == 0.0
