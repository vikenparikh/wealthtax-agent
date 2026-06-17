"""US §121 principal-residence gain exclusion.

IRC §121: a filer may exclude up to $250,000 ($500,000 MFJ) of capital gain on
the sale of a principal residence owned and used as their main home for 2 of the
last 5 years. The $250k/$500k caps are fixed (non-indexed since 1997). The
excluded gain is removed from taxable income AND from the NIIT base (it is never
in gross income). v1: the filer asserts eligibility and reports the home-sale
gain inside their long-term capital gain; principal_residence_gain says how much
of it to exclude. Previously the engine taxed the full home-sale gain.
"""
from wealthtax_agent.engines.us_engine import compute_us_return
from wealthtax_agent.state import FormExtract


def _sch_d(ltcg: float):
    return [FormExtract(form_code="SCH-D", jurisdiction="US",
                        fields={"net_long_term_capital_gain": ltcg})]


def test_gain_under_cap_fully_excluded():
    base = compute_us_return(_sch_d(200000.0), 2024, user_answers={})
    d = compute_us_return(_sch_d(200000.0), 2024,
                          user_answers={"principal_residence_gain": "200000"})
    # Single cap $250k -> full $200k excluded -> taxable LTCG drops to 0.
    assert d.line_items["section_121_exclusion"] == 200000.0
    assert d.line_items["long_term_capital_gain"] == 0.0
    assert d.line_items["federal_tax"] < base.line_items["federal_tax"]


def test_gain_over_single_cap_only_excess_taxed():
    d = compute_us_return(_sch_d(400000.0), 2024,
                          user_answers={"principal_residence_gain": "400000"})
    # Single cap $250k -> excluded $250k, taxable LTCG = $150,000.
    assert d.line_items["section_121_exclusion"] == 250000.0
    assert d.line_items["long_term_capital_gain"] == 150000.0


def test_mfj_500k_cap():
    d = compute_us_return(_sch_d(450000.0), 2024,
                          user_answers={"filing_status": "mfj", "principal_residence_gain": "450000"})
    # MFJ cap $500k -> full $450k excluded.
    assert d.line_items["section_121_exclusion"] == 450000.0
    assert d.line_items["long_term_capital_gain"] == 0.0


def test_excluded_gain_not_in_niit_base():
    # High income so MAGI is over the $200k NIIT threshold.
    w2 = [FormExtract(form_code="W-2", jurisdiction="US", fields={"wages": 300000.0})]
    extracts = w2 + _sch_d(400000.0)
    no_excl = compute_us_return(extracts, 2024, user_answers={})
    excl = compute_us_return(extracts, 2024, user_answers={"principal_residence_gain": "250000"})
    # Excluding $250k of gain reduces the NIIT base -> NIIT is strictly lower.
    assert excl.line_items["niit"] < no_excl.line_items["niit"]
    assert excl.line_items["niit"] > 0.0  # the residual $150k gain still incurs NIIT


def test_over_asserted_exclusion_clamps_to_zero_not_negative():
    d = compute_us_return(_sch_d(100000.0), 2024,
                          user_answers={"principal_residence_gain": "250000"})
    # Asserted exclusion exceeds the actual gain present -> long_gain clamps to 0.
    assert d.line_items["long_term_capital_gain"] == 0.0
    assert d.line_items["section_121_exclusion"] == 100000.0  # capped at the gain actually present


def test_no_principal_residence_gain_no_exclusion():
    d = compute_us_return(_sch_d(200000.0), 2024, user_answers={})
    assert d.line_items.get("section_121_exclusion", 0.0) == 0.0
    assert d.line_items["long_term_capital_gain"] == 200000.0
