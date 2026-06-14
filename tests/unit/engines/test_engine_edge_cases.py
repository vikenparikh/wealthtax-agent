"""Edge-branch coverage for the CA/US/IN tax engines.

Gaps surfaced by a fan-out audit subagent; every expected value was confirmed
by running the engines read-only. Covers IN age brackets / 80E 8-year cutoff /
87A boundary / new-regime 24b disallowance / cess-on-CG / NR foreign other-income
/ 2024 single-rate LTCG; US CTC phase-out / prior-loss ordinary offset / SE
Social-Security cap; and CA prior-loss gain offset.
"""

from wealthtax_agent.engines.ca_engine import compute_ca_return
from wealthtax_agent.engines.in_engine import compute_in_return
from wealthtax_agent.engines.us_engine import compute_us_return
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
