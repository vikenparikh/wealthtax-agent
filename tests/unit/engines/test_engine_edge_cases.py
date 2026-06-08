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
