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
    """Pre: ₹80k LTCG (exempt), Post: ₹2L LTCG → ₹75k taxable at 12.5%."""
    extracts = [_stock_gain(ltcg_equity_pre_change=80000, ltcg_equity_post_change=200000)]
    draft = compute_in_return(extracts, year=2025, regime="new", user_answers={"age": "30"})
    # Pre: 80k exempt (< 1L). Post: 200k - 125k threshold = 75k taxable at 12.5% = 9375
    assert draft.line_items["tax_ltcg_equity"] == 9375.0


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
