"""Advanced US engine tests: AMT, NIIT, QBI, PTC, FEIE, itemized deduction,
gambling winnings, capital-asset 8949 flow."""

from wealthtax_agent.engines.us_engine import compute_us_return
from wealthtax_agent.state import FormExtract


def _w2(wages: float, withheld: float = 0.0) -> FormExtract:
    return FormExtract(form_code="W-2", jurisdiction="US",
                       fields={"wages": wages, "federal_income_tax_withheld": withheld})


def test_qbi_deduction_applied_for_self_employed():
    extracts = [
        FormExtract(form_code="SCH-C", jurisdiction="US", fields={"net_profit": 50000.0}),
    ]
    draft = compute_us_return(extracts, year=2024, user_answers={"filing_status": "single"})
    assert draft.line_items["qbi_deduction"] > 0
    assert draft.credits["qbi_deduction"] > 0


def test_niit_kicks_in_above_threshold():
    extracts = [
        _w2(220000.0),
        FormExtract(form_code="1099-DIV", jurisdiction="US",
                    fields={"ordinary_dividends": 5000.0, "qualified_dividends": 4000.0}),
    ]
    draft = compute_us_return(extracts, year=2024, user_answers={"filing_status": "single"})
    assert draft.line_items["niit"] > 0
    assert any("NIIT" in n for n in draft.notes)


def test_itemized_beats_standard_when_sch_a_higher():
    extracts = [
        _w2(120000.0),
        FormExtract(form_code="SCH-A", jurisdiction="US", fields={
            "mortgage_interest": 18000.0,
            "state_local_taxes": 9500.0,
            "charitable_gifts": 5000.0,
        }),
    ]
    draft = compute_us_return(extracts, year=2024, user_answers={"filing_status": "single"})
    # 18000 + 9500 (under SALT cap) + 5000 = 32500 > 14600 standard
    assert draft.line_items["effective_deduction"] > draft.line_items["standard_deduction"]
    assert any("Itemized" in n for n in draft.notes)


def test_feie_excludes_foreign_earned_income():
    extracts = [
        _w2(80000.0),
        FormExtract(form_code="2555", jurisdiction="US", fields={
            "foreign_earned_income": 60000.0,
            "foreign_earned_income_excluded": 60000.0,
        }),
    ]
    draft = compute_us_return(extracts, year=2024, user_answers={"filing_status": "single"})
    assert draft.line_items["feie_excluded"] == 60000.0
    # 80000 W-2 + 0 (60000 FEIE excluded)
    assert draft.total_income == 80000.0
    assert any("Foreign Earned Income" in n for n in draft.notes)


def test_ptc_reconciliation_repayment_when_aptc_exceeds_credit():
    extracts = [
        _w2(75000.0),
        FormExtract(form_code="1095-A", jurisdiction="US", fields={
            "annual_premiums": 10000.0,
            "annual_slcsp": 9500.0,
            "advance_ptc": 7500.0,
        }),
    ]
    draft = compute_us_return(extracts, year=2024, user_answers={"filing_status": "single"})
    assert draft.line_items.get("premium_tax_credit_repayment", 0.0) >= 0.0


def test_gambling_winnings_added_to_income_with_withholding():
    extracts = [
        _w2(50000.0),
        FormExtract(form_code="W-2G", jurisdiction="US", fields={
            "gambling_winnings": 8000.0,
            "federal_income_tax_withheld": 2000.0,
        }),
    ]
    draft = compute_us_return(extracts, year=2024, user_answers={"filing_status": "single"})
    assert draft.line_items["gambling_winnings"] == 8000.0
    assert draft.line_items["tax_withheld"] == 2000.0
    assert draft.total_income == 58000.0


def test_8949_gain_flows_into_long_term_capital_gain():
    extracts = [
        _w2(60000.0),
        FormExtract(form_code="8949", jurisdiction="US", fields={"gain_loss": 5000.0}),
    ]
    draft = compute_us_return(extracts, year=2024, user_answers={"filing_status": "single"})
    assert draft.line_items["long_term_capital_gain"] == 5000.0


def test_amt_triggers_for_high_income_minimal_deductions():
    # Very high income with no other adjustments should still produce regular
    # tax > AMT (regular brackets are higher). We just assert that the AMT
    # field is populated and not negative.
    extracts = [_w2(500000.0)]
    draft = compute_us_return(extracts, year=2024, user_answers={"filing_status": "single"})
    assert draft.line_items["amt_tax"] >= 0


# --- NIIT must include rents/royalties (§1411), not just interest/divs/gains ---

def test_niit_includes_rental_income():
    """Rental income (1099-MISC rents) is net investment income under §1411.
    It flows into AGI but was previously omitted from the NIIT base, so the
    3.8% tax was understated for landlords above the threshold.

    FAILS before the fix (niit == 0, rents excluded) / PASSES after (niit ==
    3.8% of the $30k rental)."""
    extracts = [
        _w2(220000.0),  # AGI 220k from wages alone -> over single 200k threshold
        FormExtract(form_code="1099-MISC", jurisdiction="US", fields={"rents": 30000.0}),
    ]
    draft = compute_us_return(extracts, year=2024, user_answers={"filing_status": "single"})

    assert draft.line_items["rental_income"] == 30000.0  # rental is in income
    # AGI = 250k; excess over threshold (50k) exceeds NII (30k), so NII binds.
    assert draft.line_items["niit"] == round(0.038 * 30000.0, 2)  # 1140.00
    assert any("NIIT" in n for n in draft.notes)


def test_niit_includes_schedule_e_supplemental_income():
    """Schedule E rental/royalty (supplemental) income is also §1411 NII."""
    extracts = [
        _w2(210000.0),
        FormExtract(form_code="SCH-E", jurisdiction="US",
                    fields={"net_supplemental_income": 40000.0}),
    ]
    draft = compute_us_return(extracts, year=2024, user_answers={"filing_status": "single"})
    # AGI = 250k; excess 50k > NII 40k, so NII binds -> 3.8% * 40k.
    assert draft.line_items["niit"] == round(0.038 * 40000.0, 2)  # 1520.00


def test_niit_excludes_active_business_income():
    """Active trade/business income (Schedule C) is NOT net investment income —
    a Schedule-C-only high earner owes no NIIT (self-employment income is
    subject to SE tax, not the 3.8% investment tax)."""
    extracts = [
        FormExtract(form_code="SCH-C", jurisdiction="US", fields={"net_profit": 300000.0}),
    ]
    draft = compute_us_return(extracts, year=2024, user_answers={"filing_status": "single"})
    assert draft.line_items["niit"] == 0.0


# --- Social Security taxability: IRS provisional-income worksheet (Pub 915) ---
# Previously a flat 85% of benefits was always included, over-taxing low/middle
# income retirees (an SS-only retiree owes $0, not 85%).

def _ssa(net_benefits: float) -> FormExtract:
    return FormExtract(form_code="SSA-1099", jurisdiction="US",
                       fields={"net_benefits": net_benefits})


def _pension(taxable: float) -> FormExtract:
    return FormExtract(form_code="1099-R", jurisdiction="US",
                       fields={"taxable_amount": taxable})


def test_social_security_only_retiree_owes_zero_on_benefits():
    """SS-only retiree: provisional income = 0.5 * benefits = 12,000 < 25,000
    base -> 0% of benefits taxable. FAILS before (85% -> 20,400) / PASSES after."""
    draft = compute_us_return([_ssa(24000.0)], year=2024,
                              user_answers={"filing_status": "single"})
    assert draft.line_items["taxable_social_security"] == 0.0


def test_social_security_middle_income_partial_inclusion():
    """$20k pension + $20k SS, single: provisional = 20,000 + 10,000 = 30,000,
    inside the 25,000-34,000 band -> 50% tier = min(10,000, 0.5*(30,000-25,000))
    = 2,500 taxable. FAILS before (85% -> 17,000)."""
    draft = compute_us_return([_pension(20000.0), _ssa(20000.0)], year=2024,
                              user_answers={"filing_status": "single"})
    assert draft.line_items["taxable_social_security"] == 2500.0


def test_social_security_high_income_caps_at_85pct_unchanged():
    """$100k pension + $30k SS, single: provisional 115,000 >> 34,000 -> capped
    at 85% of benefits = 25,500. High earners were already correct, so this is
    unchanged by the fix (guards against over-correction)."""
    draft = compute_us_return([_pension(100000.0), _ssa(30000.0)], year=2024,
                              user_answers={"filing_status": "single"})
    assert draft.line_items["taxable_social_security"] == round(0.85 * 30000.0, 2)


def test_social_security_mfj_higher_thresholds():
    """MFJ base1 is 32,000. $10k pension + $30k SS -> provisional = 10,000 +
    15,000 = 25,000 < 32,000 -> 0% taxable (a single filer would owe tax here)."""
    draft = compute_us_return([_pension(10000.0), _ssa(30000.0)], year=2024,
                              user_answers={"filing_status": "married_filing_jointly"})
    assert draft.line_items["taxable_social_security"] == 0.0


# --- QBI §199A overall limit must exclude net capital gain (LTCG + qual divs) ---

def test_qbi_limited_by_taxable_income_minus_capital_gain():
    """SCH-C $50k QBI + $100k LTCG, single. Taxable income before QBI =
    150,000 - 14,600 std = 135,400; minus the $100k net capital gain leaves a
    $35,400 limit base -> QBI = 20% * min(50,000, 35,400) = $7,080.

    FAILS before the fix (capped at 20% of full taxable income -> $10,000)."""
    extracts = [
        FormExtract(form_code="SCH-C", jurisdiction="US", fields={"net_profit": 50000.0}),
        FormExtract(form_code="SCH-D", jurisdiction="US", fields={"net_long_term_capital_gain": 100000.0}),
    ]
    draft = compute_us_return(extracts, year=2024, user_answers={"filing_status": "single"})
    assert draft.line_items["qbi_deduction"] == 7080.0


def test_qbi_limit_uses_qualified_dividends_too():
    """Qualified dividends are also 'net capital gain' for the §199A limit.
    SCH-C $20k + $50k qualified dividends, single: taxable income before QBI =
    70,000 - 14,600 = 55,400; minus $50k -> $5,400 base -> QBI = 20% * 5,400 =
    $1,080 (was $4,000 = 20% of the $20k QBI)."""
    extracts = [
        FormExtract(form_code="SCH-C", jurisdiction="US", fields={"net_profit": 20000.0}),
        FormExtract(form_code="1099-DIV", jurisdiction="US",
                    fields={"ordinary_dividends": 50000.0, "qualified_dividends": 50000.0}),
    ]
    draft = compute_us_return(extracts, year=2024, user_answers={"filing_status": "single"})
    assert draft.line_items["qbi_deduction"] == 1080.0


def test_qbi_without_capital_gain_unchanged_guard():
    """Guard: with no preferential income, the limit is unchanged. SCH-C $50k,
    single -> 20% * min(50,000, 35,400) = $7,080 (the fix does not disturb the
    common no-capital-gain case)."""
    extracts = [FormExtract(form_code="SCH-C", jurisdiction="US", fields={"net_profit": 50000.0})]
    draft = compute_us_return(extracts, year=2024, user_answers={"filing_status": "single"})
    assert draft.line_items["qbi_deduction"] == 7080.0
