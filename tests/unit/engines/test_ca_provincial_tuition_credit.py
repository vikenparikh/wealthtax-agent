"""CA provincial tuition credit on T2202 eligible tuition fees.

#128 added the FEDERAL tuition credit (line 32300) but explicitly left the provincial
half as a follow-up. Provinces grant a parallel lowest-rate non-refundable tuition
credit (ON 5.05%); without it a student is over-taxed provincially. Mirrors the
existing provincial CPP/EI and medical credits.
"""
from wealthtax_agent.engines.ca_engine import compute_ca_return
from wealthtax_agent.state import FormExtract


def _t4(wages):
    return FormExtract(form_code="T4", jurisdiction="CA", fields={"employment_income": wages})


def _t2202(fees):
    return FormExtract(form_code="T2202", jurisdiction="CA", fields={"eligible_tuition_fees": fees})


def test_provincial_tuition_credit_at_prov_lowest_rate():
    d = compute_ca_return([_t4(50000.0), _t2202(6500.0)], year=2024, province="ON")
    # ON lowest rate 5.05% × $6,500 = $328.25
    assert d.line_items["provincial_tuition_credit"] == round(6500.0 * 0.0505, 2)


def test_provincial_tuition_credit_reduces_provincial_tax():
    base = compute_ca_return([_t4(50000.0)], year=2024, province="ON")
    with_t = compute_ca_return([_t4(50000.0), _t2202(6500.0)], year=2024, province="ON")
    assert round(base.line_items["provincial_tax"] - with_t.line_items["provincial_tax"], 2) == 328.25


def test_provincial_tuition_credit_non_refundable_floor():
    # Low-income student: provincial credits exceed provincial tax → floored at 0.
    d = compute_ca_return([_t4(13000.0), _t2202(6500.0)], year=2024, province="ON")
    assert d.line_items["provincial_tax"] == 0.0
    assert d.line_items["provincial_tuition_credit"] == 328.25


def test_no_t2202_no_provincial_regression():
    d = compute_ca_return([_t4(50000.0)], year=2024, province="ON")
    assert d.line_items["provincial_tuition_credit"] == 0.0
