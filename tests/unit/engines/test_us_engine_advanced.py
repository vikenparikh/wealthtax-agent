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
    150,000 - 3,532.39 (½ SE-tax deduction) - 14,600 std = 131,867.61; minus the
    $100k net capital gain leaves a $31,867.61 limit base -> QBI = 20% *
    min(50,000, 31,867.61) = $6,373.52.

    Net-capital-gain exclusion from the §199A limit still binds; the value also
    reflects the ½ SE-tax above-the-line deduction reducing taxable income."""
    extracts = [
        FormExtract(form_code="SCH-C", jurisdiction="US", fields={"net_profit": 50000.0}),
        FormExtract(form_code="SCH-D", jurisdiction="US", fields={"net_long_term_capital_gain": 100000.0}),
    ]
    draft = compute_us_return(extracts, year=2024, user_answers={"filing_status": "single"})
    assert draft.line_items["qbi_deduction"] == 6373.52


def test_qbi_limit_uses_qualified_dividends_too():
    """Qualified dividends are also 'net capital gain' for the §199A limit.
    SCH-C $20k + $50k qualified dividends, single: taxable income before QBI =
    70,000 - 1,412.96 (½ SE-tax deduction) - 14,600 = 53,987.04; minus $50k ->
    $3,987.04 base -> QBI = 20% * 3,987.04 = $797.41."""
    extracts = [
        FormExtract(form_code="SCH-C", jurisdiction="US", fields={"net_profit": 20000.0}),
        FormExtract(form_code="1099-DIV", jurisdiction="US",
                    fields={"ordinary_dividends": 50000.0, "qualified_dividends": 50000.0}),
    ]
    draft = compute_us_return(extracts, year=2024, user_answers={"filing_status": "single"})
    assert draft.line_items["qbi_deduction"] == 797.41


def test_qbi_without_capital_gain_unchanged_guard():
    """Guard: with no preferential income, the QBI limit is the full taxable
    income. SCH-C $50k, single -> taxable before QBI = 50,000 - 3,532.39 (½ SE
    tax) - 14,600 = 31,867.61 -> 20% * min(50,000, 31,867.61) = $6,373.52."""
    extracts = [FormExtract(form_code="SCH-C", jurisdiction="US", fields={"net_profit": 50000.0})]
    draft = compute_us_return(extracts, year=2024, user_answers={"filing_status": "single"})
    assert draft.line_items["qbi_deduction"] == 6373.52


# --- One-half self-employment tax deduction (§164(f)) ---

def test_half_se_tax_deduction_reduces_agi():
    """A self-employed filer deducts one-half of SE tax above the line (§164(f)),
    reducing AGI. SCH-C $50k net: SE earnings = 46,175; SS = 5,725.70; Medicare =
    1,339.08; half of (SS+Medicare) = $3,532.39 deduction -> AGI = $46,467.61.

    FAILS before the fix: no se_tax_deduction line item and AGI = $50,000."""
    draft = compute_us_return(
        [FormExtract(form_code="SCH-C", jurisdiction="US", fields={"net_profit": 50000.0})],
        year=2024, user_answers={"filing_status": "single"},
    )
    assert draft.line_items["se_tax_deduction"] == 3532.39
    assert draft.line_items["agi"] == 46467.61
    # The 0.9% additional Medicare is NOT part of the deductible half: here it is
    # zero, but the deduction equals exactly half of (SS + Medicare) SE tax.


def test_half_se_tax_deduction_excludes_additional_medicare():
    """The deductible half excludes the 0.9% additional Medicare surtax. High SE
    income ($300k) incurs additional Medicare, but se_tax_deduction is still
    exactly half of the SS+Medicare portion only — strictly less than half of the
    total SE tax (which includes the surtax)."""
    draft = compute_us_return(
        [FormExtract(form_code="SCH-C", jurisdiction="US", fields={"net_profit": 300000.0})],
        year=2024, user_answers={"filing_status": "single"},
    )
    se_tax = draft.line_items["self_employment_tax"]
    deduction = draft.line_items["se_tax_deduction"]
    assert deduction > 0
    # additional Medicare applies above $200k, so half of total SE tax would
    # exceed the (correct) deduction that excludes the surtax.
    assert deduction < round(0.5 * se_tax, 2)


# --- NIIT uses MAGI: foreign earned income exclusion is added back (§1411(d)) ---

def test_niit_magi_adds_back_feie_for_threshold():
    """A FEIE filer (Form 2555) excludes $150k foreign wages, so AGI = $80k from
    US interest — below the $200k NIIT threshold. But MAGI adds the exclusion
    back ($230k), so $30k of the investment income is over the threshold and the
    3.8% tax applies: $1,140.

    FAILS before the fix (AGI $80k < threshold -> niit $0)."""
    extracts = [
        FormExtract(form_code="2555", jurisdiction="US", fields={
            "foreign_earned_income": 150000.0,
            "foreign_earned_income_excluded": 150000.0,
        }),
        FormExtract(form_code="1099-INT", jurisdiction="US", fields={"interest_income": 80000.0}),
    ]
    draft = compute_us_return(extracts, year=2024, user_answers={"filing_status": "single"})
    assert draft.line_items["agi"] == 80000.0          # AGI excludes foreign wages
    assert draft.line_items["niit"] == round(0.038 * 30000.0, 2)  # 1140.00 via MAGI


def test_niit_magi_feie_filer_below_threshold_guard():
    """Guard: a FEIE filer whose MAGI is still below the threshold owes no NIIT —
    the add-back does not over-apply. $50k excluded + $40k interest -> MAGI $90k
    < $200k -> niit $0."""
    extracts = [
        FormExtract(form_code="2555", jurisdiction="US", fields={
            "foreign_earned_income": 50000.0,
            "foreign_earned_income_excluded": 50000.0,
        }),
        FormExtract(form_code="1099-INT", jurisdiction="US", fields={"interest_income": 40000.0}),
    ]
    draft = compute_us_return(extracts, year=2024, user_answers={"filing_status": "single"})
    assert draft.line_items["niit"] == 0.0


# --- 1099-DIV box 2a capital gain distributions are taxable LTCG ---

def test_1099div_capital_gain_distributions_taxed_as_ltcg():
    """1099-DIV box 2a (capital gain distributions from mutual funds/ETFs) is a
    long-term capital gain. It was captured by the extractor but never read by
    the engine, under-reporting income for fund holders.

    FAILS before the fix: long_term_capital_gain = 0."""
    extracts = [
        _w2(90000.0),
        FormExtract(form_code="1099-DIV", jurisdiction="US", fields={
            "ordinary_dividends": 2000.0,
            "qualified_dividends": 1500.0,
            "capital_gain_distributions": 8000.0,
        }),
    ]
    draft = compute_us_return(extracts, year=2024, user_answers={"filing_status": "single"})
    assert draft.line_items["long_term_capital_gain"] == 8000.0
    # and it is included in total income
    assert draft.line_items["ordinary_dividends"] == 2000.0


# --- 1099-DIV special-rate long-term gains (§1250 25%, collectibles 28%) ---

def test_unrecaptured_1250_gain_taxed_at_25pct_max():
    """1099-DIV box 2b (unrecaptured §1250 gain, e.g. from REIT/real-estate-fund
    distributions) is a subset of box 2a taxed at a MAX 25% rate, not the 0/15/20%
    LTCG rate. Captured by the extractor but ignored. Wages $250k (32% ordinary
    marginal) + box 2a $10k all §1250 → 10,000 × min(25%, 32%) = $2,500 (vs the
    $1,500 it got at the 15% LTCG rate).

    FAILS before the fix: no 'special_rate_tax' key; §1250 taxed at 15%."""
    extracts = [_w2(250000.0), FormExtract(form_code="1099-DIV", jurisdiction="US", fields={
        "capital_gain_distributions": 10000.0, "unrecaptured_section_1250_gain": 10000.0})]
    draft = compute_us_return(extracts, year=2024, user_answers={"filing_status": "single"})
    assert draft.line_items["special_rate_tax"] == 2500.0
    assert draft.line_items["unrecaptured_1250_gain"] == 10000.0
    # the line item stays gross (full box 2a), only the tax computation carves it out
    assert draft.line_items["long_term_capital_gain"] == 10000.0


def test_collectibles_gain_taxed_at_28pct_max():
    """1099-DIV box 2d (collectibles, e.g. precious-metal ETFs) is taxed at a MAX
    28%. Wages $250k (32% marginal) + box 2a $10k all collectibles → $2,800."""
    extracts = [_w2(250000.0), FormExtract(form_code="1099-DIV", jurisdiction="US", fields={
        "capital_gain_distributions": 10000.0, "collectibles_28_pct": 10000.0})]
    draft = compute_us_return(extracts, year=2024, user_answers={"filing_status": "single"})
    assert draft.line_items["special_rate_tax"] == 2800.0


def test_special_rate_gain_capped_at_ordinary_marginal_for_low_bracket():
    """The 25%/28% are MAXIMUMS — a low-bracket holder pays their ordinary marginal
    rate, not 25%/28%. Wages $40k (12% marginal) + box 2a $10k §1250 → 10,000 ×
    min(25%, 12%) = $1,200, NOT a naive $2,500. (§1250 still doesn't get the 0%
    LTCG rate, so this is higher than the buggy LTCG treatment — the correct
    direction — but capped at the ordinary 12%.)"""
    extracts = [_w2(40000.0), FormExtract(form_code="1099-DIV", jurisdiction="US", fields={
        "capital_gain_distributions": 10000.0, "unrecaptured_section_1250_gain": 10000.0})]
    draft = compute_us_return(extracts, year=2024, user_answers={"filing_status": "single"})
    assert draft.line_items["special_rate_tax"] == 1200.0


def test_early_withdrawal_penalty_is_above_line_deduction():
    """1099-INT box 2 (penalty on early withdrawal of savings, e.g. cashing a CD
    early) is an above-the-line deduction (Schedule 1 line 18). It was captured
    but never deducted, overstating AGI.

    FAILS before the fix: no early_withdrawal_penalty line item; AGI unreduced."""
    base = [_w2(90000.0)]
    with_pen = [
        _w2(90000.0),
        FormExtract(form_code="1099-INT", jurisdiction="US", fields={
            "interest_income": 3000.0,
            "early_withdrawal_penalty": 500.0,
        }),
    ]
    d0 = compute_us_return(base, year=2024, user_answers={"filing_status": "single"})
    d1 = compute_us_return(with_pen, year=2024, user_answers={"filing_status": "single"})

    assert d1.line_items["early_withdrawal_penalty"] == 500.0
    # AGI = wages 90k + interest 3k - 500 penalty = 92,500 (vs 90k baseline)
    assert d1.line_items["agi"] == 90000.0 + 3000.0 - 500.0


def test_salt_includes_w2_state_income_tax_for_itemizer():
    """W-2 box 17 state income tax withheld is part of SALT (Schedule A line 5a)
    — usually the largest component. The engine read only the Sch A field, so an
    itemizer who uploaded a W-2 (box 17) but no Sch A state-tax entry lost it.

    FAILS before the fix: salt_deduction_capped = 0 (W-2 box 17 ignored)."""
    extracts = [
        FormExtract(form_code="W-2", jurisdiction="US", fields={
            "wages": 200000.0, "federal_income_tax_withheld": 30000.0,
            "state_income_tax": 9000.0,
        }),
        FormExtract(form_code="SCH-A", jurisdiction="US", fields={"mortgage_interest": 20000.0}),
    ]
    draft = compute_us_return(extracts, year=2024, user_answers={"filing_status": "single"})
    assert draft.line_items["salt_deduction_capped"] == 9000.0  # W-2 box 17 now in SALT


def test_salt_prefers_schedule_a_total_over_w2_no_double_count():
    """When the user supplies the Schedule A state/local total it is used as-is
    (it already includes withholding) — the W-2 box 17 is not added on top."""
    extracts = [
        FormExtract(form_code="W-2", jurisdiction="US", fields={
            "wages": 200000.0, "state_income_tax": 9000.0,
        }),
        FormExtract(form_code="SCH-A", jurisdiction="US", fields={
            "mortgage_interest": 20000.0, "state_local_taxes": 7000.0,
        }),
    ]
    draft = compute_us_return(extracts, year=2024, user_answers={"filing_status": "single"})
    assert draft.line_items["salt_deduction_capped"] == 7000.0  # Sch A total, not 7000+9000
def test_excess_social_security_tax_credited_for_multiple_employers():
    """Two employers each withhold SS tax on wages near the cap; combined SS tax
    withheld exceeds the annual maximum (6.2% * 168,600 = 10,453.20). The excess
    is a refundable credit. Captured (W-2 box 4) but never applied before.

    FAILS before the fix: excess Social Security tax not credited."""
    w2 = lambda w, ss: FormExtract(form_code="W-2", jurisdiction="US",
                                   fields={"wages": w, "social_security_tax_withheld": ss})
    extracts = [w2(120000.0, 7440.0), w2(120000.0, 7440.0)]  # 14,880 withheld
    draft = compute_us_return(extracts, year=2024, user_answers={"filing_status": "single"})
    assert draft.line_items["excess_social_security_tax"] == round(14880.0 - 0.062 * 168600, 2)  # 4,426.80
    assert any("Excess Social Security" in n for n in draft.notes)


def test_excess_social_security_tax_not_credited_for_single_employer():
    """Guard: a single employer's over-withholding is the employer's to correct,
    not a refundable credit — no excess SS credit with one W-2."""
    extracts = [FormExtract(form_code="W-2", jurisdiction="US",
                            fields={"wages": 250000.0, "social_security_tax_withheld": 15000.0})]
    draft = compute_us_return(extracts, year=2024, user_answers={"filing_status": "single"})
    assert draft.line_items["excess_social_security_tax"] == 0.0
def test_ss_provisional_income_includes_tax_exempt_interest():
    """§86 adds tax-exempt interest (1099-INT box 8) back into provisional income
    for Social Security taxability — it was captured but omitted, understating
    the taxable portion of benefits for retirees with muni bonds.

    $10k pension + $20k SS + $20k tax-exempt interest, single: provisional =
    10,000 + 20,000 + 0.5*20,000 = 40,000 -> 85% tier -> $9,600 taxable.
    FAILS before the fix: provisional 20,000 < base -> $0 taxable."""
    extracts = [
        _pension(10000.0),
        _ssa(20000.0),
        FormExtract(form_code="1099-INT", jurisdiction="US",
                    fields={"tax_exempt_interest": 20000.0}),
    ]
    draft = compute_us_return(extracts, year=2024, user_answers={"filing_status": "single"})
    assert draft.line_items["taxable_social_security"] == 9600.0
    # the muni interest itself is NOT added to taxable income
    assert draft.line_items["interest_income"] == 0.0
