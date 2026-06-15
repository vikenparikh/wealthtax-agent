"""Edge-branch coverage for the CA/US/IN tax engines.

Gaps surfaced by a fan-out audit subagent; every expected value was confirmed
by running the engines read-only. Covers IN age brackets / 80E 8-year cutoff /
87A boundary / new-regime 24b disallowance / cess-on-CG / NR foreign other-income
/ 2024 single-rate LTCG; US CTC phase-out / prior-loss ordinary offset / SE
Social-Security cap; and CA prior-loss gain offset.
"""

from wealthtax_agent.config.tax_tables import load_tables
from wealthtax_agent.engines.ca_engine import compute_ca_return
from wealthtax_agent.engines.in_engine import compute_in_return
from wealthtax_agent.engines.us_engine import _compute_amt, _compute_ptc, compute_us_return
from wealthtax_agent.state import FormExtract


def _f(code, juris, **fields):
    return FormExtract(form_code=code, jurisdiction=juris, fields=fields)


# --- India engine ------------------------------------------------------------


def test_in_super_senior_80plus_bracket():
    d = compute_in_return([_f("FORM-16", "IN", gross_salary=900000)], 2024, regime="old", user_answers={"age": "82"})
    assert d.line_items["slab_tax"] == 70000.0  # 500k @0% + remainder @20%


def test_in_senior_60_to_80_bracket():
    d = compute_in_return([_f("FORM-16", "IN", gross_salary=900000)], 2024, regime="old", user_answers={"age": "65"})
    assert d.line_items["slab_tax"] == 80000.0


def test_in_80e_disallowed_after_eight_years():
    base = dict(year=2024, regime="old")
    over = compute_in_return([_f("FORM-16", "IN", gross_salary=1000000)], **base,
                             user_answers={"age": "30", "student_loan_interest_in": "50000", "years_since_first_80e": "9"})
    at = compute_in_return([_f("FORM-16", "IN", gross_salary=1000000)], **base,
                           user_answers={"age": "30", "student_loan_interest_in": "50000", "years_since_first_80e": "8"})
    assert over.line_items["section_80e"] == 0.0
    assert at.line_items["section_80e"] == 50000.0  # 8 years still allowed


def test_in_87a_rebate_inclusive_at_threshold():
    d = compute_in_return([_f("FORM-16", "IN", gross_salary=750000)], 2024, regime="new", user_answers={"age": "30"})
    assert d.totals["taxable_income"] == 700000.0
    assert d.line_items["rebate_87a"] == 25000.0
    assert d.totals["total_tax"] == 0.0


def test_in_new_regime_disallows_section_24b_self_occupied():
    d = compute_in_return([_f("FORM-16", "IN", gross_salary=1000000)], 2024, regime="new",
                          user_answers={"age": "30", "home_loan_interest_self_occupied": "200000"})
    assert d.line_items["section_24b_self_occupied"] == 0.0
    assert d.line_items["income_house_property"] == 0.0


def test_in_cess_applied_over_slab_plus_capital_gains():
    d = compute_in_return([_f("FORM-16", "IN", gross_salary=800000), _f("STOCK-GAIN", "IN", ltcg_other=500000)],
                          2024, regime="new", user_answers={"age": "30"})
    assert d.line_items["slab_tax"] == 30000.0
    assert d.line_items["capital_gains_tax"] == 100000.0
    assert d.line_items["cess"] == 5200.0
    assert d.totals["total_tax"] == 135200.0


def test_in_nr_excludes_foreign_source_other_income():
    d = compute_in_return([_f("FORM-16A", "IN", interest_income=100000)], 2024, regime="new",
                          user_answers={"age": "30", "foreign_source_other_income": "40000"}, residency_status="NR")
    assert d.line_items["other_income_total"] == 60000.0


def test_in_2024_ltcg_other_single_rate():
    d = compute_in_return([_f("STOCK-GAIN", "IN", ltcg_other=500000)], 2024, regime="new", user_answers={"age": "30"})
    assert d.line_items["tax_ltcg_other"] == 100000.0  # 20% single-rate (no 2024 split)
    assert d.line_items["ltcg_other_total"] == 500000.0


# --- US engine ---------------------------------------------------------------


def test_us_ctc_partial_phaseout_above_start():
    d = compute_us_return([_f("W-2", "US", wages=210000)], 2024, user_answers={"filing_status": "single", "num_dependents": "1"})
    assert d.line_items["child_tax_credit"] == 1500.0  # 2000 base - 500 phase-out


def test_us_prior_capital_loss_ordinary_offset_capped_at_3000():
    d = compute_us_return([_f("W-2", "US", wages=60000)], 2024, user_answers={"filing_status": "single", "prior_capital_losses": "8000"})
    assert d.line_items["capital_loss_ordinary_offset"] == 3000.0
    assert d.total_income == 57000.0


def test_us_se_social_security_capped_when_w2_over_wage_base():
    d = compute_us_return([_f("W-2", "US", wages=170000), _f("1099-NEC", "US", nonemployee_compensation=50000)],
                          2024, user_answers={"filing_status": "single"})
    assert d.line_items["self_employment_tax"] == 1484.65  # SS portion 0; Medicare + additional only


# --- CA engine ---------------------------------------------------------------


def test_ca_prior_capital_losses_fully_offset_gains():
    d = compute_ca_return([_f("T5008", "CA", capital_gain=10000)], 2024, province="ON", user_answers={"prior_capital_losses": "15000"})
    assert d.line_items["net_capital_gains"] == 0.0
    assert d.line_items["taxable_capital_gains"] == 0.0
    assert any("prior-year capital losses" in n for n in d.notes)


# --- US current-year capital-loss limitation (§1211) + short/long netting (§1222) ---

def test_us_current_year_net_capital_loss_deducts_3000_with_carryover():
    """A $5,000 current-year short-term loss (no prior carryover) deducts $3,000
    against ordinary income and carries $2,000 forward. Before the fix the loss
    vanished entirely (max(0, -5000) = 0, ordinary_offset = 0)."""
    d = compute_us_return(
        [_f("W-2", "US", wages=80000), _f("SCH-D", "US", net_short_term_capital_gain=-5000)],
        2024, user_answers={"filing_status": "single"},
    )
    assert d.line_items["capital_loss_ordinary_offset"] == 3000.0
    assert d.line_items["capital_loss_carryover"] == 2000.0
    assert d.line_items["short_term_capital_gain"] == 0.0


def test_us_long_term_loss_nets_against_short_term_gain():
    """§1222: a $4,000 long-term loss offsets a $10,000 short-term gain → net
    $6,000 short-term gain. Before the fix each was floored at 0 independently,
    so income was overstated ($10,000 taxed, $4,000 loss ignored)."""
    d = compute_us_return(
        [_f("SCH-D", "US", net_short_term_capital_gain=10000, net_long_term_capital_gain=-4000)],
        2024, user_answers={"filing_status": "single"},
    )
    assert d.line_items["short_term_capital_gain"] == 6000.0
    assert d.line_items["long_term_capital_gain"] == 0.0
    assert d.line_items["capital_loss_ordinary_offset"] == 0.0


def test_us_long_term_loss_exceeding_short_gain_becomes_limited_net_loss():
    """$2,000 short gain + $9,000 long loss → $7,000 net loss → $3,000 deducted,
    $4,000 carried forward. Before the fix the $2,000 short gain was taxed and
    the $9,000 long loss ignored."""
    d = compute_us_return(
        [_f("SCH-D", "US", net_short_term_capital_gain=2000, net_long_term_capital_gain=-9000)],
        2024, user_answers={"filing_status": "single"},
    )
    assert d.line_items["capital_loss_ordinary_offset"] == 3000.0
    assert d.line_items["capital_loss_carryover"] == 4000.0
    assert d.line_items["short_term_capital_gain"] == 0.0
    assert d.line_items["long_term_capital_gain"] == 0.0


def test_us_both_gains_positive_unchanged_guard():
    """Guard: when both characters are gains, netting leaves them untouched —
    the fix does not disturb the common all-gains case."""
    d = compute_us_return(
        [_f("SCH-D", "US", net_short_term_capital_gain=5000, net_long_term_capital_gain=8000)],
        2024, user_answers={"filing_status": "single"},
    )
    assert d.line_items["short_term_capital_gain"] == 5000.0
    assert d.line_items["long_term_capital_gain"] == 8000.0
    assert d.line_items["capital_loss_ordinary_offset"] == 0.0
    assert d.line_items["capital_loss_carryover"] == 0.0


# --- India §87A rebate marginal relief (new regime) ---

def test_in_87a_marginal_relief_just_above_threshold():
    """New regime, gross salary ₹760k → taxable ₹710k (just over the ₹700k 87A
    threshold). Normal tax = ₹26,000 but only ₹10,000 of income is above the
    threshold, so marginal relief caps tax at ₹10,000 (rebate ₹16,000).

    FAILS before the fix: income > threshold → no rebate → ₹26,000 tax (the
    cliff)."""
    d = compute_in_return([_f("FORM-16", "IN", gross_salary=760000)], 2024,
                          regime="new", user_answers={"age": "30"})
    assert d.totals["taxable_income"] == 710000.0
    assert d.line_items["rebate_87a"] == 16000.0
    # tax after rebate ₹10,000 + 4% cess = ₹10,400 (no surcharge at this income)
    assert d.totals["total_tax"] == 10400.0


def test_in_87a_marginal_relief_self_limits_for_higher_income():
    """Guard: well above the relief band the relief is 0 — income above the
    threshold (₹150k) exceeds the normal tax (₹40k), so no rebate applies and
    higher incomes are unchanged by the fix."""
    d = compute_in_return([_f("FORM-16", "IN", gross_salary=900000)], 2024,
                          regime="new", user_answers={"age": "30"})
    assert d.totals["taxable_income"] == 850000.0
    assert d.line_items["rebate_87a"] == 0.0
# --- US CTC phase-out rounds the excess UP (§24(b)(2) "or fraction thereof") ---

def test_us_ctc_phaseout_rounds_partial_thousand_up():
    """AGI $200,500 (single, 1 child) is $500 over the $200,000 threshold. Under
    §24(b)(2) a partial $1,000 counts as a full step → $50 reduction → CTC $1,950.

    FAILS before the fix: floor((500)/1000)=0 → no reduction → CTC $2,000."""
    d = compute_us_return([_f("W-2", "US", wages=200500)], 2024,
                          user_answers={"filing_status": "single", "num_dependents": "1"})
    assert d.line_items["child_tax_credit"] == 1950.0


def test_us_ctc_phaseout_exact_thousand_unchanged_guard():
    """Guard: an exact $1,000 multiple over the threshold is unaffected by the
    rounding change. AGI $205,000 → $5,000 over → 5 steps → $250 reduction →
    CTC $1,750 (same before and after)."""
    d = compute_us_return([_f("W-2", "US", wages=205000)], 2024,
                          user_answers={"filing_status": "single", "num_dependents": "1"})
    assert d.line_items["child_tax_credit"] == 1750.0


# --- US: Additional Child Tax Credit (refundable portion, Form 8812) ---

def test_us_actc_refundable_when_tax_too_low_to_absorb_ctc():
    """Single filer, $20k wages, 2 children. CTC = $4,000 but tax (~$540 on $5,400
    taxable) absorbs only $540, leaving $3,460 unused. The refundable ACTC is
    15% of earned income over $2,500 = 0.15 * (20000 - 2500) = $2,625 (less than
    both the $3,460 unused and the 2 * $1,700 = $3,400 per-child cap).

    FAILS before the fix: ACTC not computed → low-income family gets $0 refund."""
    d = compute_us_return([_f("W-2", "US", wages=20000)], 2024,
                          user_answers={"filing_status": "single", "num_dependents": "2"})
    assert d.line_items["additional_child_tax_credit"] == 2625.0
    assert d.totals["refund"] == 2625.0


def test_us_actc_limited_by_earned_income_floor():
    """Very low earned income binds the 15%-over-$2,500 limit. $5k wages, 2 kids:
    earned limit = 0.15 * (5000 - 2500) = $375, far below the unused CTC and the
    per-child cap → ACTC capped at $375 (the §24 earned-income guardrail)."""
    d = compute_us_return([_f("W-2", "US", wages=5000)], 2024,
                          user_answers={"filing_status": "single", "num_dependents": "2"})
    assert d.line_items["additional_child_tax_credit"] == 375.0


def test_us_actc_zero_when_ctc_fully_absorbed_guard():
    """Guard: $200k wages, 2 children. Tax liability dwarfs the $4,000 CTC, so it
    is fully used non-refundably → no unused portion → ACTC $0 (no double-dip)."""
    d = compute_us_return([_f("W-2", "US", wages=200000)], 2024,
                          user_answers={"filing_status": "single", "num_dependents": "2"})
    assert d.line_items["additional_child_tax_credit"] == 0.0


# --- US: allocated tips (W-2 box 8) added to taxable income, box 7 not double-counted ---

def test_us_allocated_tips_added_to_taxable_wages():
    """W-2 box 8 (allocated tips) is NOT included in box 1 wages; the IRS requires
    it reported as income (Form 1040 line 1c). The engine read only box 1, so a
    tipped worker's allocated tips escaped income tax entirely (under-taxation).

    FAILS before the fix: line_items has no 'allocated_tips' key (KeyError) and the
    $5,000 of tips produces no additional tax."""
    base = compute_us_return([_f("W-2", "US", wages=80000)], 2024,
                             user_answers={"filing_status": "single"})
    tipped = compute_us_return([_f("W-2", "US", wages=80000, allocated_tips=5000)], 2024,
                               user_answers={"filing_status": "single"})
    assert tipped.line_items["allocated_tips"] == 5000.0
    # $5,000 more taxable income, taxed at the 2024 single 22% marginal bracket.
    assert round(tipped.totals["total_tax"] - base.totals["total_tax"], 2) == 1100.0


def test_us_social_security_tips_box7_not_double_counted():
    """Guard: W-2 box 7 (Social Security tips) IS already included in box 1 wages,
    so it must NOT be added to income again. Only box 8 (allocated tips) is excluded
    from box 1. Adding box 7 would over-tax reported-tip employees."""
    base = compute_us_return([_f("W-2", "US", wages=80000)], 2024,
                             user_answers={"filing_status": "single"})
    with_box7 = compute_us_return([_f("W-2", "US", wages=80000, social_security_tips=3000)], 2024,
                                  user_answers={"filing_status": "single"})
    assert with_box7.totals["total_tax"] == base.totals["total_tax"]


# --- US: additional standard deduction for age 65+ / blind (Form 1040) ---

def test_us_additional_standard_deduction_age_65_single():
    """A single filer 65 or older gets an extra standard-deduction box ($1,950 for
    2024). The engine applied only the base standard deduction, over-taxing every
    senior who takes the standard deduction.

    FAILS before the fix: senior std deduction stays at $14,600 (no age bump)."""
    base = compute_us_return([_f("W-2", "US", wages=50000)], 2024,
                             user_answers={"filing_status": "single"})
    senior = compute_us_return([_f("W-2", "US", wages=50000)], 2024,
                               user_answers={"filing_status": "single",
                                             "taxpayer_age_65_or_older": "true"})
    assert base.line_items["standard_deduction"] == 14600.0
    assert senior.line_items["standard_deduction"] == 16550.0  # 14600 + 1950
    # $1,950 more deduction at the 12% single bracket = $234 less tax.
    assert round(base.totals["total_tax"] - senior.totals["total_tax"], 2) == 234.0


def test_us_additional_standard_deduction_mfj_age_and_blind_boxes():
    """MFJ, both spouses 65+ and one blind = 3 boxes x $1,550 (2024 married rate)
    = $4,650 on top of the $29,200 base."""
    d = compute_us_return([_f("W-2", "US", wages=80000)], 2024,
                          user_answers={"filing_status": "mfj",
                                        "taxpayer_age_65_or_older": "yes",
                                        "spouse_age_65_or_older": "yes",
                                        "taxpayer_blind": "yes"})
    assert d.line_items["standard_deduction"] == 33850.0  # 29200 + 3 * 1550


def test_us_additional_std_spouse_boxes_ignored_when_single():
    """Guard: spouse age/blind boxes only count for MFJ. A single filer who passes
    spouse flags must NOT receive the spouse's additional deductions."""
    d = compute_us_return([_f("W-2", "US", wages=50000)], 2024,
                          user_answers={"filing_status": "single",
                                        "spouse_age_65_or_older": "yes",
                                        "spouse_blind": "yes"})
    assert d.line_items["standard_deduction"] == 14600.0  # spouse boxes ignored


# --- CA: federal age amount credit (line 30100), age 65+ with income phase-out ---

def test_ca_age_amount_credit_full_below_threshold():
    """A taxpayer 65+ with net income below the year's threshold gets the full
    federal age amount ($8,790 for 2024) credited at the lowest rate (15%) =
    $1,318.50. The engine had no age amount, over-taxing every senior.

    FAILS before the fix: no 'age_amount_credit' line item; tax unchanged by age."""
    base = compute_ca_return([_f("T4", "CA", employment_income=40000)], 2024, province="ON")
    senior = compute_ca_return([_f("T4", "CA", employment_income=40000)], 2024, province="ON",
                               user_answers={"taxpayer_age_65_or_older": "true"})
    assert senior.line_items["age_amount_credit"] == 1318.50   # 8790 * 0.15
    assert round(base.totals["total_tax"] - senior.totals["total_tax"], 2) == 1318.50


def test_ca_age_amount_credit_phased_out_by_net_income():
    """Above the threshold the age amount is reduced by 15% of net income over it.
    Net income $64,325 is $20,000 over the $44,325 (2024) threshold → age amount
    $8,790 − 0.15·$20,000 = $5,790 → credit $5,790·0.15 = $868.50."""
    senior = compute_ca_return([_f("T4", "CA", employment_income=64325)], 2024, province="ON",
                               user_answers={"taxpayer_age_65_or_older": "true"})
    assert senior.line_items["age_amount_credit"] == 868.50


def test_ca_age_amount_zero_when_under_65():
    """Guard: no age flag (under 65) → no age amount credit."""
    d = compute_ca_return([_f("T4", "CA", employment_income=40000)], 2024, province="ON")
    assert d.line_items["age_amount_credit"] == 0.0


# --- CA: pension income amount (line 31400) includes RRIF income only at 65+ ---

def test_ca_pension_income_amount_includes_rrif_at_65():
    """RRIF income (T4RIF) is eligible pension income for the line 31400 amount
    only once the taxpayer is 65+. A 65+ retiree whose income comes from a RRIF
    (the standard RRSP→RRIF path, often with no employer superannuation) was
    denied the credit because RRIF was excluded outright.

    FAILS before the fix: RRIF excluded → pension_income_credit = $0."""
    d = compute_ca_return([_f("T4RIF", "CA", taxable_amount=10000)], 2024, province="ON",
                          user_answers={"taxpayer_age_65_or_older": "true"})
    assert d.line_items["pension_income_credit"] == 300.0  # min(10000, 2000) * 0.15


def test_ca_pension_income_amount_excludes_rrif_under_65():
    """Guard: under 65, RRIF income does NOT qualify for the pension income amount
    (only superannuation/periodic RPP does), so no credit on RRIF-only income."""
    d = compute_ca_return([_f("T4RIF", "CA", taxable_amount=10000)], 2024, province="ON")
    assert d.line_items["pension_income_credit"] == 0.0


def test_ca_pension_income_amount_caps_combined_super_and_rrif_at_65():
    """At 65+, superannuation and RRIF income share the single $2,000 base (not
    double-counted): $1,200 T4A + $5,000 RRIF → min($6,200, $2,000)·15% = $300."""
    d = compute_ca_return([_f("T4A", "CA", pension_or_superannuation=1200),
                           _f("T4RIF", "CA", taxable_amount=5000)], 2024, province="ON",
                          user_answers={"taxpayer_age_65_or_older": "true"})
    assert d.line_items["pension_income_credit"] == 300.0  # min(6200, 2000) * 0.15


# --- CA: OAS clawback (recovery tax) threshold is year-specific, not a 2024 constant ---

def test_ca_oas_clawback_uses_2023_threshold():
    """The OAS recovery-tax threshold was hardcoded to the 2024 value ($90,997)
    for every year. The 2023 threshold is $86,912, so a 2023 retiree with net
    income between the two was wrongly given NO clawback (under-taxation).

    FAILS before the fix: 2023 uses $90,997 → $89,000 < threshold → clawback $0."""
    d = compute_ca_return([_f("T4A", "CA", pension_or_superannuation=89000)], 2023, province="ON")
    # 2023 threshold $86,912; $89,000 is $2,088 over → 15% = $313.20.
    assert d.line_items["oas_clawback"] == 313.20


def test_ca_oas_clawback_uses_2025_threshold():
    """The 2025 threshold is $93,454, so a 2025 retiree at $92,000 net income owes
    NO clawback — but the hardcoded $90,997 wrongly clawed back (over-taxation)."""
    d = compute_ca_return([_f("T4A", "CA", pension_or_superannuation=92000)], 2025, province="ON")
    assert d.line_items["oas_clawback"] == 0.0


def test_ca_oas_clawback_2024_unchanged():
    """Regression guard: 2024 keeps the $90,997 threshold. $95,000 net → $4,003
    over → 15% = $600.45."""
    d = compute_ca_return([_f("T4A", "CA", pension_or_superannuation=95000)], 2024, province="ON")
    assert d.line_items["oas_clawback"] == 600.45


# --- US: AMT exemption / phaseout / rate breakpoint are year-specific (Form 6251) ---

def test_us_amt_exemption_single_is_year_specific():
    """The AMT exemption is indexed annually (single: 2023 $81,300, 2024 $85,700).
    The engine hardcoded the 2024 constants for every year, so a 2023 AMT payer's
    exemption was overstated by $4,400 → AMT understated by $4,400·26% = $1,144.

    FAILS before the fix: _compute_amt ignores fed_tables → 2023 == 2024."""
    amt_2023 = _compute_amt(300000.0, 0.0, "single", load_tables("us", 2023))
    amt_2024 = _compute_amt(300000.0, 0.0, "single", load_tables("us", 2024))
    # AMTI $300k is below the phaseout and the 26%/28% breakpoint in both years.
    assert round(amt_2023 - amt_2024, 2) == 1144.0  # (85700 - 81300) * 0.26


def test_us_amt_exemption_mfj_is_year_specific():
    """MFJ exemption: 2023 $126,500 vs 2024 $133,300 → 2023 AMT higher by
    (133300 - 126500)·26% = $1,768 at an AMTI below the breakpoint."""
    amt_2023 = _compute_amt(300000.0, 0.0, "married_filing_jointly", load_tables("us", 2023))
    amt_2024 = _compute_amt(300000.0, 0.0, "married_filing_jointly", load_tables("us", 2024))
    assert round(amt_2023 - amt_2024, 2) == 1768.0


def test_us_amt_2024_values_unchanged():
    """Regression guard: 2024 single, AMTI $300k, below phaseout & breakpoint →
    ($300,000 − $85,700)·26% = $55,718."""
    assert _compute_amt(300000.0, 0.0, "single", load_tables("us", 2024)) == 55718.0


# --- US: Premium Tax Credit FPL base is year-specific (Form 8962) ---

def test_us_ptc_fpl_base_year_specific_2023():
    """The PTC poverty-line base is indexed annually (a coverage year uses the
    prior calendar year's HHS guidelines): 1-person base 2023 $13,590 / 2024
    $14,580 / 2025 $15,060. Same inputs in different years land at a different
    FPL% and therefore a different applicable figure / credit.

    Single, AGI $35,000, $12,000 premiums/SLCSP, no APTC. 2023 base → FPL% 2.575
    → applicable figure 4.302% → credit $10,494.41; the 2024 base (FPL% 2.401 →
    3.602%) gives $10,739.23 (see the 2024 case) — proving the base is year-
    specific. (Values reflect the piecewise-linear applicable-figure ramp.)"""
    credit, repay = _compute_ptc(12000.0, 12000.0, 0.0, 35000.0, 0, "single", load_tables("us", 2023))
    assert (credit, repay) == (10494.41, 0.0)


def test_us_ptc_fpl_base_year_specific_2025():
    """Single, AGI $37,000. 2025 base ($15,060) → FPL% 2.457 → applicable figure
    3.827% → credit $10,583.88, distinct from what the 2024 base would yield —
    the FPL base is year-specific."""
    credit, repay = _compute_ptc(12000.0, 12000.0, 0.0, 37000.0, 0, "single", load_tables("us", 2025))
    assert (credit, repay) == (10583.88, 0.0)


def test_us_ptc_fpl_base_2024():
    """2024 single, AGI $35,000 → FPL% 2.401 → applicable figure 3.602% →
    credit $10,739.23 (contrast the 2023 base case at the same inputs)."""
    credit, repay = _compute_ptc(12000.0, 12000.0, 0.0, 35000.0, 0, "single", load_tables("us", 2024))
    assert (credit, repay) == (10739.23, 0.0)


# --- US: PTC applicable percentage is a piecewise-linear ramp, not a step table ---
# 2024 single FPL base = $14,580; aptc = 0 so credit == ptc. Values per Form 8962
# Table 2 anchors: (150%,0) (200%,2%) (250%,4%) (300%,6%) (400%,8.5%), cap 8.5%.

def test_us_ptc_applicable_pct_at_300pct_fpl_is_6pct_not_step():
    """At exactly 300% FPL the old step function charged 8.5% (it fell into the
    300–400% bucket), but the real applicable figure is 6.0%. AGI $43,740 →
    expected contribution $2,624.40 → credit $5,575.60.

    FAILS before: step table → 8.5% → $3,717.90 contribution → credit $4,482.10."""
    credit, repay = _compute_ptc(9000.0, 8200.0, 0.0, 43740.0, 0, "single", load_tables("us", 2024))
    assert (credit, repay) == (5575.60, 0.0)


def test_us_ptc_applicable_pct_interpolates_within_tier_275pct():
    """275% FPL interpolates inside the 250–300% tier: 4% + 0.5·(6%−4%) = 5.0%.
    AGI $40,095 → $2,004.75 contribution → credit $5,495.25.

    FAILS before: flat 6% bucket → $2,405.70 → credit $5,094.30."""
    credit, repay = _compute_ptc(8000.0, 7500.0, 0.0, 40095.0, 0, "single", load_tables("us", 2024))
    assert (credit, repay) == (5495.25, 0.0)


def test_us_ptc_applicable_pct_at_200pct_boundary_is_2pct():
    """Exact 200% FPL boundary → 2.0%. AGI $29,160 → $583.20 → credit $5,916.80.

    FAILS before: step table used the bucket's upper value 4% → credit $5,333.60."""
    credit, repay = _compute_ptc(7000.0, 6500.0, 0.0, 29160.0, 0, "single", load_tables("us", 2024))
    assert (credit, repay) == (5916.80, 0.0)


def test_us_ptc_no_cliff_above_400pct_caps_at_8_5pct():
    """Guard (no subsidy cliff, 2021–2025): 450% FPL stays at the 8.5% cap and the
    credit is still available. AGI $65,610 → $5,576.85 → credit $3,423.15. This
    value is unchanged by the fix (the old `else` branch already used 8.5%)."""
    credit, repay = _compute_ptc(10000.0, 9000.0, 0.0, 65610.0, 0, "single", load_tables("us", 2024))
    assert (credit, repay) == (3423.15, 0.0)


# --- CA: Canada Workers Benefit (Schedule 6), refundable, single-filer federal v1 ---

def test_ca_cwb_full_basic_amount_below_phaseout():
    """A low-income worker (working income $15,000, no other deductions so net
    income = $15,000) gets the full 2024 federal CWB basic max of $1,518: the 27%
    phase-in (0.27·($15,000−$3,000) = $3,240) is capped at the max, and net income
    is below the $26,149 phase-out threshold. The engine had no CWB at all, so this
    refundable credit never reduced the balance / increased the refund.

    FAILS before the fix: no 'canada_workers_benefit' line item (KeyError)."""
    d = compute_ca_return([_f("T4", "CA", employment_income=15000)], 2024, province="ON")
    assert d.line_items["canada_workers_benefit"] == 1518.0


def test_ca_cwb_partial_phaseout():
    """Working/net income $30,000 → basic capped at $1,518, reduced by 15% of the
    $3,851 over the $26,149 threshold ($577.65) → $940.35."""
    d = compute_ca_return([_f("T4", "CA", employment_income=30000)], 2024, province="ON")
    assert d.line_items["canada_workers_benefit"] == 940.35


def test_ca_cwb_zero_below_working_income_floor():
    """Working income $2,500 ≤ $3,000 floor → ineligible → CWB $0 (guard)."""
    d = compute_ca_return([_f("T4", "CA", employment_income=2500)], 2024, province="ON")
    assert d.line_items["canada_workers_benefit"] == 0.0


def test_ca_cwb_zero_when_fully_phased_out():
    """Net income $40,000 is past the full phase-out point ($36,269 single) → $0."""
    d = compute_ca_return([_f("T4", "CA", employment_income=40000)], 2024, province="ON")
    assert d.line_items["canada_workers_benefit"] == 0.0


def test_ca_cwb_family_max_when_spouse_or_dependant():
    """With has_spouse_or_dependant, the family max ($2,616 for 2024) and family
    threshold ($29,833) apply: working/net $15,000 → full $2,616 (phase-in $3,240
    capped, below family threshold)."""
    d = compute_ca_return([_f("T4", "CA", employment_income=15000)], 2024, province="ON",
                          user_answers={"has_spouse_or_dependant": "true"})
    assert d.line_items["canada_workers_benefit"] == 2616.0


def test_ca_cwb_refundable_increases_refund():
    """CWB is refundable: with no withholding the refund = CWB minus any residual
    (here small provincial) tax, and is strictly positive — the credit is paid out,
    not merely used to reduce tax to zero."""
    d = compute_ca_return([_f("T4", "CA", employment_income=15000)], 2024, province="ON")
    assert d.totals["refund"] == round(d.line_items["canada_workers_benefit"] - d.totals["total_tax"], 2)
    assert d.totals["refund"] > 0


# --- India: house-property loss set-off against other income (§71(3A), old regime) ---

def test_in_self_occupied_home_loan_loss_sets_off_old_regime():
    """Old regime: ₹2L self-occupied home-loan interest (§24(b)) creates a ₹2L
    house-property loss that sets off against salary (§71(3A)). Salary ₹10.5L -
    ₹50k std = ₹10L; minus the ₹2L loss -> ₹8L taxable.

    FAILS before the fix: max(0, loss) discarded the loss -> ₹10L taxable."""
    d = compute_in_return([_f("FORM-16", "IN", gross_salary=1050000)], 2024,
                          regime="old",
                          user_answers={"age": "30", "home_loan_interest_self_occupied": "200000"})
    assert d.line_items["income_house_property"] == -200000.0
    assert d.totals["taxable_income"] == 800000.0


def test_in_house_property_loss_setoff_capped_at_2lakh_old_regime():
    """A house-property loss above ₹2,00,000 (here a ₹3L let-out interest loss)
    is set off only up to ₹2,00,000; the rest carries forward. Salary ₹10L
    taxable -> ₹8L (not ₹7L)."""
    d = compute_in_return([_f("FORM-16", "IN", gross_salary=1050000)], 2024,
                          regime="old",
                          user_answers={"age": "30", "home_loan_interest_let_out": "300000"})
    assert d.line_items["income_house_property"] == -300000.0
    assert d.totals["taxable_income"] == 800000.0  # set-off capped at 2L
    assert any("carries forward" in n for n in d.notes)


def test_in_new_regime_no_house_property_loss_setoff_guard():
    """Guard: the new regime disallows self-occupied §24(b) entirely, so no loss
    arises and none is set off — salary is taxed in full."""
    d = compute_in_return([_f("FORM-16", "IN", gross_salary=1050000)], 2024,
                          regime="new",
                          user_answers={"age": "30", "home_loan_interest_self_occupied": "200000"})
    assert d.line_items["income_house_property"] == 0.0
    assert d.totals["taxable_income"] == 1000000.0


# --- India: professional tax deduction from salary (§16(iii), old regime) ---

def test_in_professional_tax_deducted_old_regime():
    """Professional tax paid is deductible from salary under §16(iii), old regime.
    Salary ₹10.5L - ₹50k std - ₹2,500 PT = ₹9,97,500 taxable.

    FAILS before the fix: no professional tax deduction -> ₹10L taxable."""
    d = compute_in_return([_f("FORM-16", "IN", gross_salary=1050000)], 2024,
                          regime="old",
                          user_answers={"age": "30", "professional_tax_paid": "2500"})
    assert d.line_items["professional_tax_deduction"] == 2500.0
    assert d.totals["taxable_income"] == 997500.0


def test_in_professional_tax_capped_at_2500():
    """The deduction is capped at ₹2,500 (constitutional ceiling on the levy)."""
    d = compute_in_return([_f("FORM-16", "IN", gross_salary=1050000)], 2024,
                          regime="old",
                          user_answers={"age": "30", "professional_tax_paid": "9000"})
    assert d.line_items["professional_tax_deduction"] == 2500.0


def test_in_professional_tax_disallowed_new_regime_guard():
    """Guard: §16(iii) professional tax is not allowed in the new regime."""
    d = compute_in_return([_f("FORM-16", "IN", gross_salary=1050000)], 2024,
                          regime="new",
                          user_answers={"age": "30", "professional_tax_paid": "2500"})
    assert d.line_items["professional_tax_deduction"] == 0.0
    assert d.totals["taxable_income"] == 1000000.0


# --- India: a capital loss must not offset salary/other income (§70/§71) ---

def test_in_capital_loss_does_not_reduce_slab_tax():
    """A short-term capital LOSS (entered negative) must not reduce tax on
    salary — capital losses can only offset capital gains and carry forward.
    Salary ₹10.5L with a ₹1L STCG-equity loss pays the SAME tax as salary alone.

    FAILS before the fix: cg_tax went negative (-₹15,000) and cut total tax."""
    base = compute_in_return([_f("FORM-16", "IN", gross_salary=1050000)], 2024,
                             regime="old", user_answers={"age": "30"})
    with_loss = compute_in_return(
        [_f("FORM-16", "IN", gross_salary=1050000), _f("STOCK-GAIN", "IN", stcg_equity=-100000)],
        2024, regime="old", user_answers={"age": "30"})
    assert with_loss.line_items["tax_stcg_equity"] <= 0.0      # the raw component is still a loss
    assert with_loss.totals["total_tax"] == base.totals["total_tax"]  # but tax is unchanged


def test_in_capital_loss_still_nets_against_capital_gain():
    """Legal intra-capital-gains netting is preserved: a ₹50k STCG-equity loss
    offsets a ₹2L LTCG-equity gain within the capital-gains tax (the total floor
    only prevents a NET loss from spilling onto salary)."""
    only_gain = compute_in_return(
        [_f("FORM-16", "IN", gross_salary=600000), _f("STOCK-GAIN", "IN", ltcg_equity=200000)],
        2024, regime="old", user_answers={"age": "30"})
    gain_and_loss = compute_in_return(
        [_f("FORM-16", "IN", gross_salary=600000),
         _f("STOCK-GAIN", "IN", ltcg_equity=200000, stcg_equity=-50000)],
        2024, regime="old", user_answers={"age": "30"})
    # the STCG loss reduces the capital-gains tax (legal netting), so total tax
    # is lower than gain-only but still strictly positive cg contribution.
    assert gain_and_loss.totals["total_tax"] < only_gain.totals["total_tax"]


def test_in_stcg_other_loss_does_not_reduce_salary():
    """A non-equity STCG loss (slab-rate category) must not reduce salary income."""
    base = compute_in_return([_f("FORM-16", "IN", gross_salary=1050000)], 2024,
                             regime="old", user_answers={"age": "30"})
    with_loss = compute_in_return(
        [_f("FORM-16", "IN", gross_salary=1050000), _f("STOCK-GAIN", "IN", stcg_other=-80000)],
        2024, regime="old", user_answers={"age": "30"})
    assert with_loss.totals["total_tax"] == base.totals["total_tax"]


def test_in_professional_tax_read_from_form16_extract():
    """Professional tax reported ON Form 16 (the primary upload path) must be
    deducted, not only a manual user answer. §16(iii), old regime.

    FAILS before the fix: the engine read only user_answers['professional_tax_paid'],
    so a form-uploaded amount was ignored -> ₹10L taxable."""
    d = compute_in_return(
        [_f("FORM-16", "IN", gross_salary=1050000, professional_tax=2500)],
        2024, regime="old", user_answers={"age": "30"})
    assert d.line_items["professional_tax_deduction"] == 2500.0
    assert d.totals["taxable_income"] == 997500.0


def test_in_80d_declared_total_is_deducted():
    """A single declared 80D total (health insurance) on Form 16 / wizard must be
    deducted — the engine read only the granular self/parents premiums, dropping
    a declared amount (inconsistent with 80C, which reads its declared total).

    FAILS before the fix: section_80d = 0 -> ₹10L taxable."""
    d = compute_in_return(
        [_f("FORM-16", "IN", gross_salary=1050000, section_80d_declared=25000)],
        2024, regime="old", user_answers={"age": "30"})
    assert d.line_items["section_80d"] == 25000.0
    # 1,000,000 salary-after-std - 25,000 (80D) = 975,000
    assert d.totals["taxable_income"] == 975000.0


def test_in_80d_declared_capped_at_combined_ceiling():
    """The declared 80D is capped at the combined self+parents ceiling
    (25,000 + 25,000 = 50,000 for non-seniors)."""
    d = compute_in_return(
        [_f("FORM-16", "IN", gross_salary=1050000, section_80d_declared=90000)],
        2024, regime="old", user_answers={"age": "30"})
    assert d.line_items["section_80d"] == 50000.0


def test_in_80ccd2_employer_nps_deducted_new_regime():
    """80CCD(2) — the employer's NPS contribution — is deductible under the NEW
    regime (it is the one Chapter VI-A item not disallowed there). It was never
    implemented, so new-regime filers with employer NPS were over-taxed.

    FAILS before the fix: no section_80ccd_2 line item; taxable income unreduced."""
    # basic_salary 800k -> 10% cap = 80k; employer NPS 60k is under the cap.
    d = compute_in_return(
        [_f("FORM-16", "IN", gross_salary=1050000, basic_salary=800000)],
        2024, regime="new",
        user_answers={"age": "30", "section_80ccd_2_employer_nps": "60000"})
    assert d.line_items["section_80ccd_2_employer_nps"] == 60000.0
    # new regime: salary 1,050,000 - 50,000 std = 1,000,000; minus 60,000 80CCD(2)
    assert d.totals["taxable_income"] == 940000.0


def test_in_80ccd2_capped_at_10pct_of_basic_salary():
    """80CCD(2) is capped at 10% of salary; an employer contribution above that
    is limited."""
    d = compute_in_return(
        [_f("FORM-16", "IN", gross_salary=1050000, basic_salary=600000)],
        2024, regime="new",
        user_answers={"age": "30", "section_80ccd_2_employer_nps": "200000"})
    assert d.line_items["section_80ccd_2_employer_nps"] == 60000.0  # 10% of 600k


def test_in_87a_base_rebate_does_not_offset_ltcg_tax():
    """§87A rebate (income at/under the threshold) must not zero out tax on
    equity LTCG (u/s 112A) — it applies to normal/slab tax only. New regime,
    salary-based total income ₹6L (under ₹7L) + ₹2L equity LTCG: slab tax
    ₹15,000 is rebated, but the ₹10,000 LTCG tax (₹1L taxable @ 10%) survives.

    FAILS before the fix: rebate = min(slab+LTCG tax, 25,000) zeroed total tax."""
    d = compute_in_return([
        _f("FORM-16", "IN", gross_salary=650000),
        _f("STOCK-GAIN", "IN", ltcg_equity=200000),
    ], 2024, regime="new", user_answers={"age": "30"})
    assert d.line_items["rebate_87a"] == 15000.0          # slab tax only (was 25,000)
    assert d.totals["total_tax"] == round(10000 * 1.04, 2)  # LTCG ₹10k + 4% cess = ₹10,400


def test_in_ltcg_equity_annual_exemption_not_doubled_across_jul23():
    """The §112A LTCG-equity exemption is annual (₹1.25L for AY2025-26), not one
    per pre/post-Jul-23-2024 period. A taxpayer with ₹1L equity LTCG before and
    ₹1L after gets ONE ₹1.25L exemption -> ₹75,000 taxable, not two exemptions
    (which would tax ₹0).

    FAILS before the fix: per-period exemption (₹1L pre + ₹1.25L post) exempts
    the full ₹2L -> ₹0 taxable."""
    d = compute_in_return([
        _f("FORM-16", "IN", gross_salary=600000),
        _f("STOCK-GAIN", "IN", ltcg_equity_pre_change=100000, ltcg_equity_post_change=100000),
    ], 2025, regime="new", user_answers={"age": "30"})
    # exemption applied to post (1.0L) first then pre (0.25L) -> taxable: post 0,
    # pre 75,000 @ 10% = 7,500 LTCG tax
    assert d.line_items["ltcg_equity_taxable"] == 75000.0


def test_in_ltcg_equity_post_only_gets_full_annual_exemption():
    """Guard: a post-change-only filer still gets the full ₹1.25L exemption."""
    d = compute_in_return([
        _f("FORM-16", "IN", gross_salary=600000),
        _f("STOCK-GAIN", "IN", ltcg_equity_post_change=200000),
    ], 2025, regime="new", user_answers={"age": "30"})
    assert d.line_items["ltcg_equity_taxable"] == 75000.0  # 200,000 - 125,000
