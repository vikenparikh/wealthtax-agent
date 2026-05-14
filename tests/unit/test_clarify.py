from wealthtax_agent.clarify import ask_clarifications_node
from wealthtax_agent.state import GraphState


def test_clarify_pauses_when_high_priority_answers_missing():
    state = GraphState(jurisdictions=["CA"], user_answers={})
    result = ask_clarifications_node(state)
    assert result.awaiting_clarification is True
    assert any(q.priority == "high" for q in result.clarifying_questions)


def test_clarify_does_not_pause_when_answers_already_provided():
    state = GraphState(
        jurisdictions=["CA"],
        user_answers={
            "marital_status": "single",
            "province_of_residence": "ON",
            "foreign_property_over_100k": "no",
        },
    )
    result = ask_clarifications_node(state)
    assert result.awaiting_clarification is False


def test_clarify_emits_us_questions_for_us_jurisdiction():
    state = GraphState(jurisdictions=["US"], user_answers={})
    result = ask_clarifications_node(state)
    ids = {q.id for q in result.clarifying_questions}
    assert "filing_status" in ids
    assert "num_dependents" in ids
