"""AMT × non-refundable-credit interaction (§55/§26/§59).

Regression tests for a money-path bug in ``us_engine`` where the AMT block
compared the tentative minimum tax (TMT) against the *credit-reduced* federal
tax and, on a spurious trigger, overwrote ``federal_tax = TMT`` — throwing away
every non-refundable credit (FTC/CTC/ODC/education/...).

The statutory rule (§55): AMT is the excess of TMT over the *regular tax before
credits*, added on top; the non-refundable credits are still allowed against the
combined liability. So in the normal case:

    federal_tax == max(regular_before_credits, TMT) - non_refundable_credits

These tests assert (a) no spurious AMT trigger when regular > TMT and credits are
preserved, (b) same for a CTC family, and (c) that a genuine AMT (TMT > regular)
is *added* while credits are still subtracted.
"""

from wealthtax_agent.engines.us_engine import compute_us_return
from wealthtax_agent.state import FormExtract


def _w2(wages: float, withheld: float = 0.0) -> FormExtract:
    return FormExtract(
        form_code="W-2",
        jurisdiction="US",
        fields={"wages": wages, "federal_income_tax_withheld": withheld},
    )


# --- (a) MFJ + FTC: regular tax exceeds TMT → true AMT is $0, FTC must survive ---
def test_mfj_ftc_no_spurious_amt_and_ftc_preserved():
    """MFJ, $320k W-2 wages, $100k foreign-source income, $25k foreign tax paid, 2024.

    regular tax before credits ≈ $55,877 EXCEEDS TMT ≈ $48,542 → statutory AMT = $0.
    The §904-limited FTC is $19,214.92, so correct federal_tax ≈ 55,877 − 19,214.92
    = $36,662.08.

    Fails-before: the engine fired AMT and overwrote federal_tax to the TMT
    ($48,542.00), forfeiting the entire FTC (over-charge ≈ $11,880).
    """
    extracts = [_w2(320000.0)]
    ua = {
        "filing_status": "married_filing_jointly",
        "foreign_source_income": "100000",
        "foreign_tax_paid": "25000",
    }
    draft = compute_us_return(extracts, year=2024, user_answers=ua)

    ftc = draft.line_items["foreign_tax_credit"]
    assert ftc == 19214.92  # §904-limited credit is computed correctly

    # AMT must NOT fire — regular tax (before credits) exceeds TMT.
    assert draft.line_items["amt_tax"] == 0.0

    # The FTC must be preserved: regular_before_credits ($55,877) − FTC.
    assert round(draft.line_items["federal_tax"], 2) == round(55877.0 - ftc, 2)


# --- (b) CTC family: regular tax exceeds TMT → CTC must survive, no AMT ---
def test_ctc_family_no_spurious_amt_and_ctc_preserved():
    """MFJ, $150k wages, two qualifying children. Regular tax comfortably exceeds
    TMT (moderate income, standard deduction), so AMT must not fire and the full
    $4,000 CTC ($2,000 × 2) must reduce the tax.
    """
    extracts = [_w2(150000.0)]
    ua = {
        "filing_status": "married_filing_jointly",
        "num_dependents": "2",  # all dependents default to CTC qualifying children
    }
    with_ctc = compute_us_return(extracts, year=2024, user_answers=ua)
    without = compute_us_return(
        extracts, year=2024, user_answers={"filing_status": "married_filing_jointly"}
    )

    assert with_ctc.line_items["amt_tax"] == 0.0
    ctc = with_ctc.line_items["child_tax_credit"]
    assert ctc == 4000.0
    # The CTC must reduce federal_tax by exactly the credit amount.
    assert round(with_ctc.line_items["federal_tax"], 2) == round(
        without.line_items["federal_tax"] - ctc, 2
    )


# --- (c) Genuine AMT: TMT exceeds regular tax → AMT is ADDED, credits preserved ---
def test_genuine_amt_added_on_top_and_credits_preserved():
    """Single, $250k wages, $120k itemized deduction (mortgage interest).

    Regular taxable income = $130k, so regular tax is modest, but AMT adds the
    $120k deduction back into AMTI → TMT ≈ $42,718 EXCEEDS regular tax before
    credits. So AMT genuinely applies (amt_additional > 0).

    With the fix, the AMT add-on lifts federal_tax to the TMT, and a
    non-refundable FTC must STILL be subtracted from the combined liability —
    the credit is not forfeited.
    """
    extracts = [
        _w2(250000.0),
        FormExtract(
            form_code="SCH-A",
            jurisdiction="US",
            fields={"mortgage_interest": 120000.0},
        ),
    ]
    # Baseline with no credits: genuine AMT lifts federal_tax to the TMT ($42,718).
    no_credit = compute_us_return(
        extracts, year=2024, user_answers={"filing_status": "single"}
    )
    assert no_credit.line_items["amt_tax"] > 0.0  # AMT genuinely applies (added on top)
    assert no_credit.line_items["federal_tax"] == 42718.0

    # Now add an FTC; the credit must survive the AMT.
    with_ftc = compute_us_return(
        extracts,
        year=2024,
        user_answers={
            "filing_status": "single",
            "foreign_source_income": "40000",
            "foreign_tax_paid": "8000",
        },
    )
    ftc = with_ftc.line_items["foreign_tax_credit"]
    assert ftc > 0.0
    # AMT still applies (added on top) and the FTC is still subtracted.
    assert with_ftc.line_items["amt_tax"] > 0.0
    assert round(with_ftc.line_items["federal_tax"], 2) == round(
        no_credit.line_items["federal_tax"] - ftc, 2
    )


# --- (d) AMT + credits > regular tax: credits offset the AMT too (§26(a)/§59(a)) ---
def test_amt_with_credits_exceeding_regular_tax_credits_offset_amt():
    """When a genuine AMT applies AND non-refundable credits EXCEED the regular
    tax, the credits (allowed against AMT) must offset the COMBINED regular+AMT
    tax — the filer is not over-taxed.

    Case: single, $250k wages, $120k mortgage interest (→ regular tax before
    credits $24,242.50, TMT $42,718 so AMT applies), $100k foreign-source income
    with $50k foreign tax (§904-limited FTC $18,648.08) + $100k clean-energy cost
    (§25D $30,000). Credits $48,648 exceed the combined tax
    max($24,242.50, $42,718) = $42,718, so the whole liability is absorbed →
    federal_tax $0.00.

    (Before the pre-credit-AMT fix this over-taxed by $18,475.50 — the AMT add-on
    with the excess credit lost to the max(0, ...) floor. This test is that fix.)
    """
    extracts = [
        _w2(250000.0),
        FormExtract(form_code="SCH-A", jurisdiction="US",
                    fields={"mortgage_interest": 120000.0}),
    ]
    d = compute_us_return(extracts, year=2024, user_answers={
        "filing_status": "single",
        "foreign_source_income": "100000",
        "foreign_tax_paid": "50000",
        "residential_clean_energy_cost": "100000",
    })
    assert d.line_items["federal_tax"] == 0.0
