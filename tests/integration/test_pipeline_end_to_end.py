import wealthtax_agent.explain_return as explain_return
import wealthtax_agent.graph as graph
import wealthtax_agent.parse_docs as parse_docs
from wealthtax_agent.state import GraphState


class _Msg:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Msg(content)


class _Resp:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _Completions:
    def __init__(self, content):
        self.content = content

    def create(self, **kwargs):
        return _Resp(self.content)


class _Chat:
    def __init__(self, content):
        self.completions = _Completions(content)


class _Client:
    def __init__(self, content):
        self.chat = _Chat(content)


def test_pipeline_end_to_end_happy_path(monkeypatch):
    monkeypatch.setattr(parse_docs, "ocr_bytes_to_text", lambda _doc, _mime: "synthetic slip text")
    monkeypatch.setattr(
        parse_docs,
        "llm_parse",
        lambda _text: {
            "slips": [
                {"type": "T4", "fields": {"employment_income": 80000.0}},
                {"type": "T5", "fields": {"interest_income": 1000.0, "dividends": 500.0}},
                {"type": "RRSP", "fields": {"rrsp_contributions": 7000.0}},
            ]
        },
    )
    monkeypatch.setattr(
        explain_return,
        "client",
        _Client('{"lines": {"total_income": "sum of slip incomes", "estimated_tax": "simplified estimate"}}'),
    )

    compiled = graph.build_graph()
    output = compiled.invoke(GraphState(raw_docs=[b"doc-a", b"doc-b"]))
    final_state = GraphState.model_validate(output)

    assert final_state.draft_return is not None
    assert final_state.draft_return.total_income == 163000.0
    assert final_state.draft_return.rrsp_deduction == 14000.0
    assert final_state.draft_return.taxable_income == 149000.0
    assert final_state.draft_return.estimated_tax == 37250.0
    assert final_state.explanation is not None
    assert "total_income" in final_state.explanation.lines


def test_pipeline_end_to_end_parse_failure_still_returns_state(monkeypatch):
    monkeypatch.setattr(parse_docs, "ocr_bytes_to_text", lambda _doc, _mime: "bad")

    def _raise(_text):
        raise ValueError("parse failure")

    monkeypatch.setattr(parse_docs, "llm_parse", _raise)
    monkeypatch.setattr(
        explain_return,
        "client",
        _Client("not-json"),
    )

    compiled = graph.build_graph()
    output = compiled.invoke(GraphState(raw_docs=[b"doc-a"]))
    final_state = GraphState.model_validate(output)

    assert final_state.draft_return is not None
    assert final_state.draft_return.total_income == 0.0
    assert len(final_state.warnings) >= 1
    assert final_state.explanation is not None
