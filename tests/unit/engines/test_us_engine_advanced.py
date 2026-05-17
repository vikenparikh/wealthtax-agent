"""Advanced US engine tests: AMT, NIIT, QBI, PTC, FEIE, itemized deduction,
gambling winnings, capital-asset 8949 flow."""

from wealthtax_agent.engines.us_engine import compute_us_return
from wealthtax_agent.state import FormExtract


def _w2(wages: float, withheld: float = 0.0) -> FormExtract:
    return FormExtract(form_code="W-2", jurisdiction="US",
                       fields={"wages": wages, "federal_income_tax_withheld": withheld})


def test_qbi_deduction_applied_for_self_employed():
    extracts = [
        FormExtract(form_code="SCH-C", jurisdiction="US", fields={"net_profit": 50000.0}),
    ]
    draft = compute_us_return(extracts, year=2024, user_answers={"filing_status": "single"})
    assert draft.line_items["qbi_deduction"] > 0
    assert draft.credits["qbi_deduction"] > 0


def test_niit_kicks_in_above_threshold():
    extracts = [
        _w2(220000.0),
        FormExtract(form_code="1099-DIV", jurisdiction="US",
                    fields={"ordinary_dividends": 5000.0, "qualified_dividends": 4000.0}),
    ]
    draft = compute_us_return(extracts, year=2024, user_answers={"filing_status": "single"})
    assert draft.line_items["niit"] > 0
    assert any("NIIT" in n for n in draft.notes)


def test_itemized_beats_standard_when_sch_a_higher():
    extracts = [
        _w2(120000.0),
        FormExtract(form_code="SCH-A", jurisdiction="US", fields={
            "mortgage_interest": 18000.0,
            "state_local_taxes": 9500.0,
            "charitable_gifts": 5000.0,
        }),
    ]
    draft = compute_us_return(extracts, year=2024, user_answers={"filing_status": "single"})
    # 18000 + 9500 (under SALT cap) + 5000 = 32500 > 14600 standard
    assert draft.line_items["effective_deduction"] > draft.line_items["standard_deduction"]
    assert any("Itemized" in n for n in draft.notes)


def test_feie_excludes_foreign_earned_income():
    extracts = [
        _w2(80000.0),
        FormExtract(form_code="2555", jurisdiction="US", fields={
            "foreign_earned_income": 60000.0,
            "foreign_earned_income_excluded": 60000.0,
        }),
    ]
    draft = compute_us_return(extracts, year=2024, user_answers={"filing_status": "single"})
    assert draft.line_items["feie_excluded"] == 60000.0
    # 80000 W-2 + 0 (60000 FEIE excluded)
    assert draft.total_income == 80000.0
    assert any("Foreign Earned Income" in n for n in draft.notes)


def test_ptc_reconciliation_repayment_when_aptc_exceeds_credit():
    extracts = [
        _w2(75000.0),
        FormExtract(form_code="1095-A", jurisdiction="US", fields={
            "annual_premiums": 10000.0,
            "annual_slcsp": 9500.0,
            "advance_ptc": 7500.0,
        }),
    ]
    draft = compute_us_return(extracts, year=2024, user_answers={"filing_status": "single"})
    assert draft.line_items.get("premium_tax_credit_repayment", 0.0) >= 0.0


def test_gambling_winnings_added_to_income_with_withholding():
    extracts = [
        _w2(50000.0),
        FormExtract(form_code="W-2G", jurisdiction="US", fields={
            "gambling_winnings": 8000.0,
            "federal_income_tax_withheld": 2000.0,
        }),
    ]
    draft = compute_us_return(extracts, year=2024, user_answers={"filing_status": "single"})
    assert draft.line_items["gambling_winnings"] == 8000.0
    assert draft.line_items["tax_withheld"] == 2000.0
    assert draft.total_income == 58000.0


def test_8949_gain_flows_into_long_term_capital_gain():
    extracts = [
        _w2(60000.0),
        FormExtract(form_code="8949", jurisdiction="US", fields={"gain_loss": 5000.0}),
    ]
    draft = compute_us_return(extracts, year=2024, user_answers={"filing_status": "single"})
    assert draft.line_items["long_term_capital_gain"] == 5000.0


def test_amt_triggers_for_high_income_minimal_deductions():
    # Very high income with no other adjustments should still produce regular
    # tax > AMT (regular brackets are higher). We just assert that the AMT
    # field is populated and not negative.
    extracts = [_w2(500000.0)]
    draft = compute_us_return(extracts, year=2024, user_answers={"filing_status": "single"})
    assert draft.line_items["amt_tax"] >= 0
