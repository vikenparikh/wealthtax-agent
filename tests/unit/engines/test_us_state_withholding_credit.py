"""US engine must credit STATE withholding (W-2 box 17), not just federal.

`total_tax` combines federal + state (+ local + SE) tax, so the balance/refund
must credit BOTH federal AND state withholding. The engine credited only
federal withholding, so a filer in a state with income tax had their refund
understated / balance owing overstated by the ENTIRE state-withholding amount.
The CA-540 artifact already credited it; this makes the engine's combined
refund/owing reconcile with (1040 net) + (540 net).
"""
from wealthtax_agent.engines.us_engine import compute_us_return
from wealthtax_agent.state import FormExtract


def _w2(wages, fed_wh, state_wh):
    return FormExtract(
        form_code="W-2", jurisdiction="US",
        fields={"wages": wages, "federal_income_tax_withheld": fed_wh,
                "state_income_tax": state_wh},
    )


def test_state_withholding_credited_reveals_refund():
    # CA resident, $150k wages, $30k federal + $15k state (box 17) withheld.
    # total tax = federal $25,538.50 + CA state $9,977.14 = $35,515.64.
    # Payments = $30k fed + $15k state = $45k > total → refund $9,484.36.
    # PRE-FIX the engine credited only the $30k federal withholding → balance
    # $5,515.64 OWING and estimated_refund $0.00 — the $15k state withholding
    # (and the whole refund) was silently dropped.
    d = compute_us_return([_w2(150000.0, 30000.0, 15000.0)], 2024, "CA",
                          {"filing_status": "single"})
    assert d.estimated_tax == 35515.64
    assert d.estimated_refund == 9484.36


def test_state_withholding_reduces_balance_owing():
    # Same CA filer but smaller withholding ($20k fed + $9k state): still owes,
    # but the owing must credit the state withholding. Reconciles with
    # (1040 net $25,538.50 - $20,000 = $5,538.50) + (540 net $9,977.14 - $9,000
    # = $977.14) = $6,515.64 owing (estimated_refund 0). Pre-fix the owing was
    # $15,515.64 (state withholding uncredited).
    d = compute_us_return([_w2(150000.0, 20000.0, 9000.0)], 2024, "CA",
                          {"filing_status": "single"})
    assert d.estimated_refund == 0.0
    # estimated_tax unchanged; the correction is in the (owing) balance, which is
    # total - fed_wh - state_wh = 35,515.64 - 20,000 - 9,000 = 6,515.64.
    assert d.estimated_tax == 35515.64


def test_balance_reconciles_with_federal_net_plus_state_net():
    # The engine's combined balance_owing must equal (1040 federal net) +
    # (CA-540 state net): (federal_tax - fed_withheld) + (state_tax - state_withheld).
    # This guards the semantics: balance_owing is the COMBINED fed+state net, and
    # the two artifacts' owing figures sum to it.
    d = compute_us_return([_w2(150000.0, 20000.0, 9000.0)], 2024, "CA",
                          {"filing_status": "single"})
    li = d.line_items
    federal_net = li["federal_tax"] - li["tax_withheld"]          # 1040 net
    state_net = li["state_tax"] - 9000.0                           # CA-540 net (box 17)
    assert round(d.totals["balance_owing"], 2) == round(federal_net + state_net, 2)


def test_no_state_no_change():
    # Federal-only filer (no state): behavior is unchanged — state withholding is
    # 0, so the balance is federal-only as before.
    d = compute_us_return([_w2(150000.0, 20000.0, 0.0)], 2024, None,
                          {"filing_status": "single"})
    assert d.estimated_refund == 0.0  # owes (federal tax > 20k withholding)
