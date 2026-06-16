"""Golden tests for the India tax engine — both regimes, surcharge tiers, LTCG split."""

from wealthtax_agent.engines.in_engine import compute_in_return
from wealthtax_agent.state import FormExtract


def _form16(**fields):
    return FormExtract(form_code="FORM-16", jurisdiction="IN", fields=fields)


def _stock_gain(**fields):
    return FormExtract(form_code="STOCK-GAIN", jurisdiction="IN", fields=fields)


# ---------- New regime ----------

def test_new_regime_salary_only_low_income():
    """Salary 5 lakh new regime — slabs 0+12.5k + 87A rebate = ₹0 tax."""
    extracts = [_form16(gross_salary=500000)]
    draft = compute_in_return(extracts, year=2024, regime="new", user_answers={"age": "30"})
    # New regime 2024: standard deduction 50k, slabs (0/5/10/15/20/30%)
    # Taxable: 500000 - 50000 = 450000 → 0% on first 300k + 5% on 150k = 7500
    # 87A rebate caps at 25000, income ≤ 700000 → rebate wipes tax to 0
    assert draft.line_items["section_80c"] == 0  # new regime ignores chapter VIA
    assert draft.line_items["rebate_87a"] == 7500.0
    assert draft.totals["total_tax"] == 0.0


def test_new_regime_high_income_no_rebate():
    """Salary 20 lakh new regime — no 87A, normal slabs apply."""
    extracts = [_form16(gross_salary=2000000)]
    draft = compute_in_return(extracts, year=2024, regime="new", user_answers={"age": "30"})
    # Taxable = 2000000 - 50000 = 1950000
    # New 2024 slabs: 0 to 3L=0, 3-6L (5%)=15000, 6-9L (10%)=30000, 9-12L (15%)=45000,
    # 12-15L (20%)=60000, 15L+ (30%) of 450000=135000 → total 285000
    assert draft.line_items["slab_tax"] == 285000.0
    # 4% cess on 285000 = 11400 → total 296400
    assert draft.totals["total_tax"] == 296400.0


# ---------- Old regime ----------

def test_old_regime_with_80c_and_80d():
    """Salary 12L old regime + 80C 1.5L + 80D 25k → lower tax than new."""
    extracts = [_form16(gross_salary=1200000)]
    answers = {
        "age": "35",
        "section_80c_ppf": "150000",
        "section_80d_self_premium": "25000",
    }
    draft = compute_in_return(extracts, year=2024, regime="old", user_answers=answers)
    # Salary income = 1200000 - 50000 = 1150000
    # After 80C(150k) + 80D(25k) = 175k → taxable 975000
    # Old slabs: 0-2.5L=0, 2.5-5L (5%)=12500, 5L-10L (20%)=100000, > none
    # Tax = 0 + 12500 + 95000 = 107500
    assert draft.line_items["section_80c"] == 150000
    assert draft.line_items["section_80d"] == 25000
    assert draft.line_items["slab_tax"] == 107500.0


def test_old_regime_80c_capped_at_150k():
    """User claims 80C ₹200k but engine must cap at ₹1.5L."""
    extracts = [_form16(gross_salary=1000000)]
    answers = {"age": "30", "section_80c_ppf": "200000"}
    draft = compute_in_return(extracts, year=2024, regime="old", user_answers=answers)
    assert draft.line_items["section_80c"] == 150000


# ---------- Auto regime ----------

def test_auto_picks_lower_tax_regime():
    """Salary 8L with no deductions → new regime cheaper."""
    extracts = [_form16(gross_salary=800000)]
    draft = compute_in_return(extracts, year=2024, regime="auto", user_answers={"age": "30"})
    # New regime: 800k - 50k = 750k; slabs 0+15+15 = 30k; 87A applies up to 7L threshold but
    # 750k > 700k, no rebate. Cess 4% → 31200.
    # Old regime: 800k - 50k = 750k; slabs 0+12.5+50 = 62500; no rebate (> 5L); cess → 65000.
    assert draft.totals["total_tax"] == 31200.0
    assert "alternate_regime_tax" in draft.line_items
    assert draft.line_items["alternate_regime_tax"] > draft.estimated_tax


# ---------- Capital gains, pre/post Jul 23 2024 ----------

def test_ltcg_equity_threshold_exempt():
    """LTCG equity ₹80k pre-change → fully exempt under ₹1L threshold."""
    extracts = [_stock_gain(ltcg_equity_pre_change=80000)]
    draft = compute_in_return(extracts, year=2025, regime="new", user_answers={"age": "30"})
    assert draft.line_items["ltcg_equity_exempt"] == 80000
    assert draft.line_items["tax_ltcg_equity"] == 0.0


def test_ltcg_equity_split_pre_and_post_change():
    """§112A exemption is a single ANNUAL amount, not one per pre/post period.

    Pre: ₹80k LTCG, Post: ₹2L LTCG. The year's ₹1.25L annual exemption is
    applied to the higher-rate post-change gains first (taxpayer-favourable),
    fully consuming it — so the pre-change ₹80k is NOT separately exempt.
    Post: 200k - 125k = 75k @ 12.5% = 9375; Pre: 80k @ 10% = 8000; total 17375.
    """
    extracts = [_stock_gain(ltcg_equity_pre_change=80000, ltcg_equity_post_change=200000)]
    draft = compute_in_return(extracts, year=2025, regime="new", user_answers={"age": "30"})
    assert draft.line_items["tax_ltcg_equity"] == 17375.0


def test_stcg_equity_pre_15_pct_post_20_pct():
    """STCG equity pre-change taxed at 15%, post-change at 20%."""
    extracts = [_stock_gain(stcg_equity_pre_change=100000, stcg_equity_post_change=100000)]
    draft = compute_in_return(extracts, year=2025, regime="new", user_answers={"age": "30"})
    # 100k * 15% + 100k * 20% = 35000
    assert draft.line_items["tax_stcg_equity"] == 35000.0


# ---------- Surcharge tiers ----------

def test_surcharge_50_lakh_tier():
    """Income just over ₹50 lakh → 10% surcharge."""
    extracts = [_form16(gross_salary=5500000)]
    draft = compute_in_return(extracts, year=2024, regime="new", user_answers={"age": "30"})
    # Verify surcharge > 0 (10% of tax)
    assert draft.line_items["surcharge"] > 0


def test_surcharge_new_regime_capped_at_25_pct():
    """Income > ₹5 crore — new regime caps surcharge at 25%, not 37%."""
    extracts = [_form16(gross_salary=60_000_000)]
    new_draft = compute_in_return(extracts, year=2024, regime="new", user_answers={"age": "30"})
    old_draft = compute_in_return(extracts, year=2024, regime="old", user_answers={"age": "30"})
    # Both have similar base; new should have lower surcharge ratio than old
    new_ratio = new_draft.line_items["surcharge"] / new_draft.line_items["slab_tax"]
    old_ratio = old_draft.line_items["surcharge"] / old_draft.line_items["slab_tax"]
    assert new_ratio <= 0.251
    assert old_ratio > new_ratio


# ---------- 87A rebate edge cases ----------

def test_87a_rebate_below_threshold():
    """Total income ≤ ₹7L (new regime) → 87A wipes out tax."""
    extracts = [_form16(gross_salary=700000)]
    draft = compute_in_return(extracts, year=2024, regime="new", user_answers={"age": "30"})
    # Income 700k - 50k std ded = 650k; rebate threshold is 700k so this qualifies
    assert draft.line_items["rebate_87a"] > 0
    assert draft.totals["total_tax"] == 0.0


def test_87a_old_regime_threshold():
    """Old regime: 87A only triggers ≤ ₹5L."""
    extracts = [_form16(gross_salary=550000)]
    answers = {"age": "30", "section_80c_ppf": "100000"}
    draft = compute_in_return(extracts, year=2024, regime="old", user_answers=answers)
    # Salary income 500k - chapter VIA 100k = 400k taxable → rebate wipes to 0
    assert draft.line_items["rebate_87a"] > 0
    assert draft.totals["total_tax"] == 0.0


# ---------- Residency awareness ----------

def test_nr_excludes_foreign_source_salary():
    """Non-resident with foreign salary flag → salary excluded."""
    extracts = [_form16(gross_salary=2000000)]
    answers = {"age": "30", "salary_is_foreign": "yes"}
    draft = compute_in_return(extracts, year=2024, regime="new",
                              user_answers=answers, residency_status="NR")
    assert draft.line_items["gross_salary"] == 0.0
    assert draft.totals["taxable_income"] == 0.0


def test_rnor_with_indian_source_only_taxed():
    """RNOR with Indian salary only — taxed normally on India-source income."""
    extracts = [_form16(gross_salary=1000000)]
    answers = {"age": "30"}
    draft = compute_in_return(extracts, year=2024, regime="new",
                              user_answers=answers, residency_status="RNOR")
    assert draft.line_items["gross_salary"] == 1000000


# ---------- Senior citizen ----------

def test_senior_uses_80ttb_not_80tta():
    """Age 65 with bank interest → 80TTB cap ₹50k applies, not 80TTA ₹10k."""
    extracts = [
        _form16(gross_salary=400000),
        FormExtract(form_code="FORM-16A", jurisdiction="IN", fields={"interest_income": 60000}),
    ]
    answers = {"age": "65"}
    draft = compute_in_return(extracts, year=2024, regime="old", user_answers=answers)
    assert draft.line_items["section_80tta_or_80ttb"] == 50000  # 80TTB cap


# ---------- HRA exemption ----------

def test_hra_exemption_metro_old_regime():
    """Mumbai (metro): HRA exempt is min(HRA, rent-10% salary, 50% salary)."""
    extracts = [_form16(gross_salary=1000000, basic_salary=600000, hra_received=200000)]
    answers = {
        "age": "30",
        "city_of_residence": "Mumbai",
        "annual_rent_paid": "240000",
    }
    draft = compute_in_return(extracts, year=2024, regime="old", user_answers=answers)
    # HRA exempt = min(200000, 240000 - 60000=180000, 0.5*600000=300000) = 180000
    assert draft.line_items["hra_exemption"] == 180000


def test_hra_not_allowed_in_new_regime():
    """HRA exemption disabled under new regime."""
    extracts = [_form16(gross_salary=1000000, basic_salary=600000, hra_received=200000)]
    answers = {
        "age": "30",
        "city_of_residence": "Mumbai",
        "annual_rent_paid": "240000",
    }
    draft = compute_in_return(extracts, year=2024, regime="new", user_answers=answers)
    assert draft.line_items["hra_exemption"] == 0


# ---------- Prepaid taxes: advance tax, self-assessment tax, TCS (Part B-TTI) ----------

def test_in_advance_tax_credited_against_liability():
    """The engine credited only TDS against the tax liability, so a filer who paid
    advance tax (the norm for business / capital-gains / professional income) saw
    the FULL liability as owing. Advance tax is a prepaid tax that reduces the
    balance owing.

    Salary 20L new regime → total_tax ₹2,96,400, no TDS. FAILS before the fix:
    line_items has no 'advance_tax' key and balance owing ignores the ₹1,00,000."""
    extracts = [_form16(gross_salary=2000000)]
    base = compute_in_return(extracts, year=2024, regime="new", user_answers={"age": "30"})
    adv = compute_in_return(extracts, year=2024, regime="new",
                            user_answers={"age": "30", "advance_tax_paid": "100000"})
    # No TDS → before any prepaid credit the entire liability is owing.
    assert base.totals["balance_owing"] == base.totals["total_tax"]
    assert adv.line_items["advance_tax"] == 100000.0
    assert adv.totals["balance_owing"] == round(base.totals["total_tax"] - 100000.0, 2)


def test_in_prepaid_taxes_combine_and_can_produce_refund():
    """Advance + self-assessment + TCS all join TDS in the taxes-paid pool; an
    overpayment produces a refund. total_tax ₹2,96,400 fully covered by advance
    tax, plus ₹15,000 self-assessment + ₹5,000 TCS overpaid → ₹20,000 refund."""
    extracts = [_form16(gross_salary=2000000)]
    tt = compute_in_return(extracts, year=2024, regime="new",
                           user_answers={"age": "30"}).totals["total_tax"]
    d = compute_in_return(extracts, year=2024, regime="new", user_answers={
        "age": "30",
        "advance_tax_paid": str(tt),
        "self_assessment_tax_paid": "15000",
        "tcs_collected": "5000",
    })
    assert d.line_items["self_assessment_tax"] == 15000.0
    assert d.line_items["tcs"] == 5000.0
    assert d.totals["total_taxes_paid"] == round(tt + 20000.0, 2)
    assert d.totals["refund"] == 20000.0
    assert d.totals["balance_owing"] == 0.0


def test_in_no_prepaid_input_is_unchanged():
    """Additive: with no prepaid inputs, total_taxes_paid == total_tds and the
    balance is byte-identical to the prior TDS-only behaviour (no regression)."""
    extracts = [_form16(gross_salary=2000000)]
    d = compute_in_return(extracts, year=2024, regime="new", user_answers={"age": "30"})
    assert d.line_items["advance_tax"] == 0.0
    assert d.totals["total_taxes_paid"] == d.line_items["total_tds"]
    assert d.totals["balance_owing"] == d.totals["total_tax"]


# ---------- §80E student-loan interest from Form 16 (old regime) ----------

def test_in_80e_read_from_form16():
    """§80E student-loan interest declared on Form 16 (box captured by the
    extractor) was dropped — the engine read §80E only from the manual
    `student_loan_interest_in` answer. A Form-16 upload now claims it (old regime),
    which also restores the cross-border single-claim guardrail (keys on
    line_items['section_80e']).

    FAILS before the fix: section_80e = 0 for a Form-16 with §80E declared."""
    d = compute_in_return([_form16(gross_salary=1000000, section_80e_declared=50000)],
                          year=2024, regime="old", user_answers={"age": "30"})
    assert d.line_items["section_80e"] == 50000.0


def test_in_80e_form_preferred_over_manual_no_double_count():
    """When both a Form-16 §80E and a manual entry are present, the form value is
    used (not summed) — no double-count."""
    d = compute_in_return([_form16(gross_salary=1000000, section_80e_declared=50000)],
                          year=2024, regime="old",
                          user_answers={"age": "30", "student_loan_interest_in": "40000"})
    assert d.line_items["section_80e"] == 50000.0


def test_in_80e_manual_still_works_without_form():
    """Regression guard: manual §80E entry (no form value) is unchanged."""
    d = compute_in_return([_form16(gross_salary=1000000)],
                          year=2024, regime="old",
                          user_answers={"age": "30", "student_loan_interest_in": "40000"})
    assert d.line_items["section_80e"] == 40000.0


# ---------- Advance tax from an uploaded Form 26AS (form-vs-manual bridge) ----------

def test_in_advance_tax_read_from_form26as():
    """Advance tax reported on an uploaded Form 26AS (captured by the extractor) was
    dropped — the engine read advance tax only from the manual `advance_tax_paid`
    answer, so a 26AS upload left it uncredited and overstated the balance owing.
    Salary 20L new regime → total_tax ₹2,96,400, no TDS; Form 26AS advance tax
    ₹1,00,000 → balance owing ₹1,96,400.

    FAILS before the fix: advance_tax = 0; balance owing ₹2,96,400."""
    d = compute_in_return([_form16(gross_salary=2000000),
                           FormExtract(form_code="FORM-26AS", jurisdiction="IN",
                                       fields={"advance_tax_paid": 100000})],
                          year=2024, regime="new", user_answers={"age": "30"})
    assert d.line_items["advance_tax"] == 100000.0
    assert d.totals["balance_owing"] == round(d.totals["total_tax"] - 100000.0, 2)


def test_in_advance_tax_form26as_preferred_over_manual_no_double_count():
    """Form 26AS value is used (not summed with the manual entry) → no double-count."""
    d = compute_in_return([_form16(gross_salary=2000000),
                           FormExtract(form_code="FORM-26AS", jurisdiction="IN",
                                       fields={"advance_tax_paid": 100000})],
                          year=2024, regime="new",
                          user_answers={"age": "30", "advance_tax_paid": "80000"})
    assert d.line_items["advance_tax"] == 100000.0
