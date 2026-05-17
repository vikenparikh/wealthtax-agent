"""Parameterized test that every supported form extractor (CA + US) pulls
non-empty fields from its fixture and classifies via the heuristic registry.

This is the "test all forms" check — one row per form, golden expectations
are kept minimal (one well-known field) so the test stays robust across
extractor tweaks.
"""

from pathlib import Path

import pytest

import wealthtax_agent.forms  # noqa: F401 - ensure registry is populated
from wealthtax_agent.classify_forms import _heuristic_classify
from wealthtax_agent.forms.registry import get


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "forms"


# (form_code, fixture relative path, jurisdiction, must-extract field, expected value)
CASES = [
    # Canada
    ("T4",      "ca/t4_sample.txt",      "CA", "employment_income",          80000.00),
    ("T5",      "ca/t5_sample.txt",      "CA", "interest_income",             1200.50),
    ("T3",      "ca/t3_sample.txt",      "CA", "capital_gains",               1500.00),
    ("T5008",   "ca/t5008_sample.txt",   "CA", "capital_gain",                2500.00),
    ("T2202",   "ca/t2202_sample.txt",   "CA", "eligible_tuition_fees",       6500.00),
    ("T4A",     "ca/t4a_sample.txt",     "CA", "pension_or_superannuation",  24000.00),
    ("RRSP",    "ca/rrsp_sample.txt",    "CA", "rrsp_contributions",          7000.00),
    ("T776",    "ca/t776_sample.txt",    "CA", "net_rental_income",          21500.00),
    ("T2125",   "ca/t2125_sample.txt",   "CA", "net_business_income",        45500.00),
    ("T2200",   "ca/t2200_sample.txt",   "CA", "employment_expenses",         3400.00),
    ("T4RSP",   "ca/t4rsp_sample.txt",   "CA", "withdrawal_and_commutation",  8000.00),
    ("T4RIF",   "ca/t4rif_sample.txt",   "CA", "taxable_amount",             12000.00),
    ("T5013",   "ca/t5013_sample.txt",   "CA", "business_income_loss",        4000.00),

    # United States
    ("W-2",       "us/w2_sample.txt",       "US", "wages",                       80000.00),
    ("1099-INT",  "us/1099_int_sample.txt", "US", "interest_income",                500.00),
    ("1099-DIV",  "us/1099_div_sample.txt", "US", "ordinary_dividends",            2000.00),
    ("1099-B",    "us/1099_b_sample.txt",   "US", "gain_loss",                     4000.00),
    ("1099-NEC",  "us/1099_nec_sample.txt", "US", "nonemployee_compensation",     15000.00),
    ("1099-MISC", "us/1099_misc_sample.txt","US", "rents",                        12000.00),
    ("1099-R",    "us/1099_r_sample.txt",   "US", "gross_distribution",           15000.00),
    ("1098",      "us/1098_sample.txt",     "US", "mortgage_interest_received",    9500.00),
    ("1098-E",    "us/1098_e_sample.txt",   "US", "student_loan_interest",         2200.00),
    ("1098-T",    "us/1098_t_sample.txt",   "US", "qualified_tuition_payments",   22500.00),
    ("SSA-1099",  "us/ssa_1099_sample.txt", "US", "net_benefits",                 24000.00),
    ("K-1",       "us/k1_sample.txt",       "US", "ordinary_business_income",     12000.00),
    ("SCH-A",     "us/sch_a_sample.txt",    "US", "mortgage_interest",             9500.00),
    ("SCH-B",     "us/sch_b_sample.txt",    "US", "total_interest",                1850.00),
    ("SCH-C",     "us/sch_c_sample.txt",    "US", "net_profit",                   57000.00),
    ("SCH-D",     "us/sch_d_sample.txt",    "US", "net_long_term_capital_gain",    6800.00),
    ("1099-K",    "us/1099_k_sample.txt",   "US", "gross_payments",               22500.00),
    ("1099-G",    "us/1099_g_sample.txt",   "US", "unemployment_compensation",     4500.00),
    ("SCH-SE",    "us/sch_se_sample.txt",   "US", "self_employment_tax",           4239.00),
    ("SCH-E",     "us/sch_e_sample.txt",    "US", "net_supplemental_income",      21500.00),
    ("8949",      "us/8949_sample.txt",     "US", "gain_loss",                     7000.00),
    ("8889",      "us/8889_sample.txt",     "US", "hsa_contributions",             4150.00),
    ("1099-SA",   "us/1099_sa_sample.txt",  "US", "gross_distribution",            1200.00),
    ("1099-Q",    "us/1099_q_sample.txt",   "US", "gross_distribution",            8000.00),
    ("5498",      "us/5498_sample.txt",     "US", "ira_contributions",             7000.00),
    ("1095-A",    "us/1095_a_sample.txt",   "US", "annual_premiums",              14400.00),
    ("W-2G",      "us/w2g_sample.txt",      "US", "gambling_winnings",             5000.00),
    ("2555",      "us/2555_sample.txt",     "US", "foreign_earned_income",        95000.00),

    # CA additions
    ("T1135",     "ca/t1135_sample.txt",    "CA", "total_foreign_property_cost", 250000.00),
    ("T2222",     "ca/t2222_sample.txt",    "CA", "residency_deduction",           4015.00),
]


@pytest.mark.parametrize("form_code, fixture_path, jurisdiction, key_field, expected_value", CASES)
def test_extractor_extracts_expected_field(form_code, fixture_path, jurisdiction, key_field, expected_value):
    extractor = get(form_code)
    assert extractor is not None, f"No registered extractor for {form_code}"
    assert extractor.jurisdiction == jurisdiction

    text = (FIXTURES / fixture_path).read_text(encoding="utf-8")
    extract = extractor.extract(text, source_filename=fixture_path)

    assert extract.form_code == form_code
    assert extract.jurisdiction == jurisdiction
    assert key_field in extract.fields, f"{form_code}: expected {key_field} in extract.fields={extract.fields}"
    assert extract.fields[key_field] == pytest.approx(expected_value), \
        f"{form_code}: {key_field} mismatch"


@pytest.mark.parametrize("form_code, fixture_path, jurisdiction, key_field, expected_value", CASES)
def test_heuristic_classifies_each_form(form_code, fixture_path, jurisdiction, key_field, expected_value):
    text = (FIXTURES / fixture_path).read_text(encoding="utf-8")
    classification = _heuristic_classify(text)
    assert classification is not None, f"Classifier missed {form_code}"
    assert classification.form_code == form_code
    assert classification.jurisdiction == jurisdiction
