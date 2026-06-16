"""CA federal tuition credit (line 32300) on T2202 eligible tuition fees.

The T2202 extractor captures eligible_tuition_fees but the engine never applied the
federal tuition credit to the student's OWN tax — only the optimizer suggested
transferring the unused portion. A working student who paid tuition and owes federal
tax was over-taxed. The credit is a lowest-rate non-refundable credit (capped at tax;
the transfer/carry-forward of any unused portion is a separate optimization).
"""
from wealthtax_agent.engines.ca_engine import compute_ca_return
from wealthtax_agent.state import FormExtract


def _t4(wages):
    return FormExtract(form_code="T4", jurisdiction="CA", fields={"employment_income": wages})


def _t2202(fees):
    return FormExtract(form_code="T2202", jurisdiction="CA", fields={"eligible_tuition_fees": fees})


def test_tuition_credit_at_lowest_rate():
    d = compute_ca_return([_t4(50000.0), _t2202(6500.0)], year=2024, province="ON")
    assert d.line_items["eligible_tuition_fees"] == 6500.0
    assert d.line_items["tuition_credit"] == round(6500.0 * 0.15, 2)  # 975.00


def test_tuition_credit_reduces_federal_tax():
    base = compute_ca_return([_t4(50000.0)], year=2024, province="ON")
    with_t = compute_ca_return([_t4(50000.0), _t2202(6500.0)], year=2024, province="ON")
    assert round(base.line_items["federal_tax"] - with_t.line_items["federal_tax"], 2) == 975.0


def test_tuition_credit_non_refundable_cannot_go_negative():
    # Low-income student: credit exceeds tax → federal tax floored at 0, no refund.
    d = compute_ca_return([_t4(12000.0), _t2202(6500.0)], year=2024, province="ON")
    assert d.line_items["federal_tax"] == 0.0
    assert d.line_items["tuition_credit"] == 975.0  # full credit still computed/surfaced


def test_no_t2202_no_regression():
    d = compute_ca_return([_t4(50000.0)], year=2024, province="ON")
    assert d.line_items["tuition_credit"] == 0.0
    assert d.line_items["eligible_tuition_fees"] == 0.0
