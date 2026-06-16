"""T4 box 46 charitable donations must feed the CA donation credit.

The T4 extractor captures box 46 (charitable_donations), but before this fix the
engine read donations only from user_answers — so a filer who uploaded a T4 with a
payroll-giving amount and trusted the slip lost the entire fed + provincial credit.
The slip value and the manual entry are merged via max() (override, no double-count).
"""
from wealthtax_agent.engines.ca_engine import compute_ca_return
from wealthtax_agent.state import FormExtract


def _t4(wages: float, **fields) -> FormExtract:
    f = {"employment_income": wages}
    f.update(fields)
    return FormExtract(form_code="T4", jurisdiction="CA", fields=f)


# Fed donation credit on $1,000: 200*0.15 + 800*0.29 = 262.00
_FED_1000 = round(200 * 0.15 + 800 * 0.29, 2)


def test_slip_only_donations_credited():
    # Box 46 = $1,000, no manual entry. Before the fix this dropped to $0 credit.
    extracts = [_t4(80000.0, charitable_donations=1000.0)]
    d = compute_ca_return(extracts, year=2024, province="ON")
    assert round(d.line_items["donations_credit"], 2) == _FED_1000
    assert d.line_items["charitable_donations"] == 1000.0
    assert d.line_items["charitable_donations_slip"] == 1000.0
    assert d.line_items["provincial_donations_credit"] > 0


def test_slip_reduces_tax_vs_no_slip():
    no_slip = compute_ca_return([_t4(80000.0)], year=2024, province="ON")
    with_slip = compute_ca_return([_t4(80000.0, charitable_donations=1000.0)],
                                  year=2024, province="ON")
    assert with_slip.estimated_tax < no_slip.estimated_tax


def test_slip_and_smaller_manual_no_double_count():
    # Box 46 = $1,000, user types 600 → max = 1,000 (NOT 1,600). No double-count.
    extracts = [_t4(80000.0, charitable_donations=1000.0)]
    d = compute_ca_return(extracts, year=2024, province="ON",
                          user_answers={"charitable_donations": "600"})
    assert d.line_items["charitable_donations"] == 1000.0
    assert round(d.line_items["donations_credit"], 2) == _FED_1000


def test_manual_larger_than_slip_overrides():
    # Box 46 = $500, user types 2,000 (added an external receipt) → max = 2,000.
    extracts = [_t4(80000.0, charitable_donations=500.0)]
    d = compute_ca_return(extracts, year=2024, province="ON",
                          user_answers={"charitable_donations": "2000"})
    expected = round(200 * 0.15 + 1800 * 0.29, 2)  # 552.00
    assert d.line_items["charitable_donations"] == 2000.0
    assert round(d.line_items["donations_credit"], 2) == expected


def test_no_donations_anywhere_zero_credit():
    d = compute_ca_return([_t4(80000.0)], year=2024, province="ON")
    assert d.line_items["donations_credit"] == 0.0
    assert d.line_items["charitable_donations"] == 0.0
    assert d.line_items["charitable_donations_slip"] == 0.0
