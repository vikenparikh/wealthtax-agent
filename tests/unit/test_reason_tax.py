from wealthtax_agent.reason_tax import reason_tax_node
from wealthtax_agent.state import GraphState, Slip


def test_reason_tax_t4_only():
    state = GraphState(slips=[Slip(type="T4", fields={"employment_income": 80000.0})])

    result = reason_tax_node(state)

    assert result.draft_return is not None
    assert result.draft_return.total_income == 80000.0
    assert result.draft_return.rrsp_deduction == 0.0
    assert result.draft_return.taxable_income == 80000.0
    assert result.draft_return.estimated_tax == 20000.0


def test_reason_tax_t5_and_rrsp_mix():
    state = GraphState(
        slips=[
            Slip(type="T4", fields={"employment_income": 50000.0}),
            Slip(type="T5", fields={"interest_income": 1000.0, "dividends": 500.0}),
            Slip(type="RRSP", fields={"rrsp_contributions": 4000.0}),
        ]
    )

    result = reason_tax_node(state)

    assert result.draft_return is not None
    assert result.draft_return.total_income == 51500.0
    assert result.draft_return.rrsp_deduction == 4000.0
    assert result.draft_return.taxable_income == 47500.0
    assert result.draft_return.estimated_tax == 11875.0


def test_reason_tax_taxable_income_floor_at_zero():
    state = GraphState(
        slips=[
            Slip(type="T4", fields={"employment_income": 3000.0}),
            Slip(type="RRSP", fields={"rrsp_contributions": 5000.0}),
        ]
    )

    result = reason_tax_node(state)

    assert result.draft_return is not None
    assert result.draft_return.total_income == 3000.0
    assert result.draft_return.taxable_income == 0.0
    assert result.draft_return.estimated_tax == 0.0


def test_reason_tax_ignores_unknown_slips():
    state = GraphState(
        slips=[
            Slip(type="UNKNOWN", fields={"employment_income": 99999.0}),
            Slip(type="T4", fields={"employment_income": 1000.0}),
        ]
    )

    result = reason_tax_node(state)

    assert result.draft_return is not None
    assert result.draft_return.total_income == 1000.0
