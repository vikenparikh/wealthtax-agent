"""Student-loan single-claim guardrail + RSU sourcing + FTC hints."""

from wealthtax_agent.engines.cross_border import (
    enforce_single_student_loan,
    foreign_tax_credit_hint,
    rsu_sourcing_split,
)
from wealthtax_agent.state import DraftReturn, GraphState


def _state_with_two_loan_claims(us_marginal: float, in_marginal: float) -> GraphState:
    state = GraphState(
        jurisdictions=["US", "IN"],
        draft_returns={
            "US": DraftReturn(
                jurisdiction="US",
                line_items={"student_loan_interest_deduction": 2500.0},
                totals={"taxable_income": 100000.0, "total_tax": 100000.0 * us_marginal},
            ),
            "IN": DraftReturn(
                jurisdiction="IN",
                line_items={"section_80e": 40000.0},
                totals={"taxable_income": 1000000.0, "total_tax": 1000000.0 * in_marginal},
            ),
        },
    )
    return state


def test_student_loan_kept_in_higher_marginal_jurisdiction_us_wins():
    state = _state_with_two_loan_claims(us_marginal=0.30, in_marginal=0.20)
    warnings = enforce_single_student_loan(state)
    assert state.draft_returns["US"].line_items["student_loan_interest_deduction"] == 2500.0
    assert state.draft_returns["IN"].line_items["section_80e"] == 0.0
    assert any("Removed from IN" in w for w in warnings)


def test_student_loan_kept_in_higher_marginal_jurisdiction_in_wins():
    state = _state_with_two_loan_claims(us_marginal=0.15, in_marginal=0.30)
    warnings = enforce_single_student_loan(state)
    assert state.draft_returns["IN"].line_items["section_80e"] == 40000.0
    assert state.draft_returns["US"].line_items["student_loan_interest_deduction"] == 0.0
    assert any("Removed from US" in w for w in warnings)


def test_no_warning_when_only_one_jurisdiction_claims_loan():
    state = GraphState(
        draft_returns={
            "US": DraftReturn(
                jurisdiction="US",
                line_items={"student_loan_interest_deduction": 2500.0},
                totals={"taxable_income": 100000.0, "total_tax": 18000.0},
            ),
            "IN": DraftReturn(
                jurisdiction="IN",
                line_items={"section_80e": 0.0},
                totals={"taxable_income": 1000000.0, "total_tax": 100000.0},
            ),
        },
    )
    warnings = enforce_single_student_loan(state)
    assert warnings == []
    assert state.draft_returns["US"].line_items["student_loan_interest_deduction"] == 2500.0


def test_rsu_sourcing_splits_by_workdays():
    """100 workdays US + 200 workdays CA + 0 IN → 1/3 US, 2/3 CA."""
    split = rsu_sourcing_split(30000.0, 100, 200)
    assert split["US"] == 10000.0
    assert split["CA"] == 20000.0
    assert split["IN"] == 0.0


def test_rsu_sourcing_handles_three_country_split():
    split = rsu_sourcing_split(60000.0, 100, 100, 100)
    assert split["US"] == 20000.0
    assert split["CA"] == 20000.0
    assert split["IN"] == 20000.0


def test_rsu_sourcing_zero_when_no_workdays():
    split = rsu_sourcing_split(50000.0, 0, 0, 0)
    assert split == {"US": 0.0, "CA": 0.0, "IN": 0.0}


def test_ftc_hint_when_resident_in_one_country_source_in_another():
    state = GraphState(
        jurisdictions=["US", "CA"],
        residency_status={"US": "nonresident", "CA": "resident"},
        draft_returns={
            "US": DraftReturn(
                jurisdiction="US",
                totals={"taxable_income": 80000.0, "total_tax": 12000.0},
            ),
            "CA": DraftReturn(
                jurisdiction="CA",
                totals={"taxable_income": 80000.0, "total_tax": 18000.0},
            ),
        },
    )
    notes = foreign_tax_credit_hint(state)
    assert any("CA resident may credit up to $12,000.00 of US tax" in n for n in notes)


def test_no_ftc_hint_with_single_jurisdiction():
    state = GraphState(
        jurisdictions=["US"],
        draft_returns={
            "US": DraftReturn(jurisdiction="US", totals={"taxable_income": 80000.0, "total_tax": 12000.0}),
        },
    )
    assert foreign_tax_credit_hint(state) == []
