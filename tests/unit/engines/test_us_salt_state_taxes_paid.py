"""SALT must honour state income tax supplied via the state_taxes_paid question.

State/local income tax for the SALT deduction was read only from Schedule A
(state_local_taxes) or W-2 box 17. A filer who pays state income tax but has
neither form line — e.g. self-employed paying estimated state tax — and answers
the `state_taxes_paid` clarifying question had that amount silently dropped from
SALT, overstating federal tax. Form sources take precedence (no double-count);
the question is the fallback.
"""
from wealthtax_agent.engines.us_engine import compute_us_return
from wealthtax_agent.state import FormExtract


def _itemizing(**ua):
    # $25k mortgage interest forces itemizing over the $14,600 single standard.
    extracts = [
        FormExtract(form_code="W-2", jurisdiction="US", fields={"wages": 150000.0}),
        FormExtract(form_code="SCH-A", jurisdiction="US", fields={"mortgage_interest": 25000.0}),
    ]
    answers = {"filing_status": "single"}
    answers.update(ua)
    return compute_us_return(extracts, 2024, user_answers=answers)


def test_state_taxes_paid_question_feeds_salt():
    base = _itemizing()
    d = _itemizing(state_taxes_paid="8000")
    # $8,000 state income tax -> SALT $8,000 (under the $10k cap).
    assert d.line_items["salt_deduction_capped"] == 8000.0
    assert d.line_items["federal_tax"] < base.line_items["federal_tax"]


def test_state_taxes_paid_respects_salt_cap():
    d = _itemizing(state_taxes_paid="9000", state_local_property_tax="5000")
    # 9,000 + 5,000 = 14,000 -> capped at $10,000.
    assert d.line_items["salt_deduction_capped"] == 10000.0


def test_w2_box17_takes_precedence_over_question_no_double_count():
    extracts = [
        FormExtract(form_code="W-2", jurisdiction="US",
                    fields={"wages": 150000.0, "state_income_tax": 5000.0}),
        FormExtract(form_code="SCH-A", jurisdiction="US", fields={"mortgage_interest": 25000.0}),
    ]
    d = compute_us_return(extracts, 2024,
                          user_answers={"filing_status": "single", "state_taxes_paid": "8000"})
    # W-2 box 17 ($5,000) is authoritative; the question does NOT add on top.
    assert d.line_items["salt_deduction_capped"] == 5000.0


def test_no_state_tax_anywhere_no_salt():
    d = _itemizing()
    assert d.line_items["salt_deduction_capped"] == 0.0
