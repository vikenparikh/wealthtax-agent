"""§87A rebate is a resident-only relief — a non-resident (NR) is barred.

Before this fix the rebate was granted on an income-threshold test alone, with no
residency gate, so an NR with India-source income at/under the threshold wrongly got
up to ₹25,000 (new) / ₹12,500 (old) of rebate they aren't entitled to. RNOR is a
*resident* under the Act (only its foreign income is exempt) and KEEPS the rebate —
the gate is on the literal "NR", not is_nr_or_rnor.
"""
from wealthtax_agent.engines.in_engine import compute_in_return
from wealthtax_agent.state import FormExtract


def _form16(**fields):
    return FormExtract(form_code="FORM-16", jurisdiction="IN", fields=fields)


# ₹6L India-source salary, new regime 2024: taxable 600000 - 50000 std = 550000;
# slab tax = 5% on (550000 - 300000) = 12500; +4% cess = 13000 when not rebated.
def _draft(residency_status):
    return compute_in_return(
        [_form16(gross_salary=600000)], year=2024, regime="new",
        user_answers={"age": "30"}, residency_status=residency_status,
    )


def test_nr_denied_87a_rebate():
    d = _draft("NR")
    assert d.line_items["rebate_87a"] == 0.0
    assert d.totals["total_tax"] == 13000.0  # 12500 slab + 4% cess, no rebate
    assert any("non-resident" in n.lower() and "87a" in n.lower() for n in d.notes)


def test_rnor_keeps_87a_rebate():
    # RNOR is resident-eligible — must NOT lose the rebate (the load-bearing distinction).
    d = _draft("RNOR")
    assert d.line_items["rebate_87a"] == 12500.0
    assert d.totals["total_tax"] == 0.0


def test_ror_default_keeps_87a_rebate():
    # The dominant single-jurisdiction population (default ROR) is untouched.
    d = _draft("ROR")
    assert d.line_items["rebate_87a"] == 12500.0
    assert d.totals["total_tax"] == 0.0


def test_nr_high_income_unchanged():
    # NR well above the threshold never had a rebate; gate changes nothing here.
    d = compute_in_return(
        [_form16(gross_salary=2000000)], year=2024, regime="new",
        user_answers={"age": "30"}, residency_status="NR",
    )
    assert d.line_items["rebate_87a"] == 0.0
    assert d.totals["total_tax"] > 0
