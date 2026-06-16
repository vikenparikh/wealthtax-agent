"""§72(t) 10% additional tax on early retirement-plan distributions (1099-R box 7).

Only box-7 code "1" (early distribution, no known exception) triggers the penalty.
Codes 2/3/4 (exception/disability/death), 7 (normal), and G/H (rollover) are exempt.
Before this fix the engine read 1099-R taxable_amount but ignored the box-7 code, so
an early distribution incurred no §72(t) penalty — under-taxing under-59½ filers.
"""
from wealthtax_agent.engines.us_engine import compute_us_return
from wealthtax_agent.state import FormExtract


def _w2(wages):
    return FormExtract(form_code="W-2", jurisdiction="US", fields={"wages": wages})


def _1099r(taxable, code):
    return FormExtract(form_code="1099-R", jurisdiction="US",
                       fields={"taxable_amount": taxable, "distribution_code": code})


def _single(*extracts):
    return compute_us_return(list(extracts), year=2024,
                             user_answers={"filing_status": "single", "num_dependents": "0"})


def test_code_1_early_distribution_incurs_10pct_penalty():
    d = _single(_w2(40000.0), _1099r(20000.0, "1"))
    assert d.line_items["early_distribution_penalty"] == 2000.0  # 10% of 20,000


def test_code_7_normal_distribution_no_penalty():
    d = _single(_w2(40000.0), _1099r(20000.0, "7"))
    assert d.line_items["early_distribution_penalty"] == 0.0


def test_exception_codes_2_3_4_no_penalty():
    for code in ("2", "3", "4"):
        d = _single(_w2(40000.0), _1099r(20000.0, code))
        assert d.line_items["early_distribution_penalty"] == 0.0, f"code {code}"


def test_code_6_section1035_exchange_no_penalty():
    # Code 6 (§1035 exchange) is not an early distribution → no penalty.
    d = _single(_w2(40000.0), _1099r(50000.0, "6"))
    assert d.line_items["early_distribution_penalty"] == 0.0


def test_penalty_is_per_form_only_early_one_penalised():
    # One early (code 1, $20k) + one normal (code 7, $30k): penalty only on the early.
    d = _single(_w2(40000.0), _1099r(20000.0, "1"), _1099r(30000.0, "7"))
    assert d.line_items["early_distribution_penalty"] == 2000.0  # 10% of 20,000 only


def test_no_1099r_no_penalty():
    d = _single(_w2(40000.0))
    assert d.line_items["early_distribution_penalty"] == 0.0


def test_penalty_increases_total_tax():
    no_pen = _single(_w2(40000.0), _1099r(20000.0, "7"))
    with_pen = _single(_w2(40000.0), _1099r(20000.0, "1"))
    # Same income (both distributions are taxable); the only difference is the penalty.
    delta = with_pen.estimated_tax - no_pen.estimated_tax
    assert round(delta, 2) == 2000.0
