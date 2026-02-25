import re
from pathlib import Path

import pytest

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


def _extract_amount(text: str, label: str) -> float:
    match = re.search(rf"{label}[^\n]*:\s*([0-9]+(?:\.[0-9]+)?)", text, flags=re.IGNORECASE)
    return float(match.group(1)) if match else 0.0


def _mock_llm_parse(text: str) -> dict:
    slips = []
    if "Employment income" in text:
        slips.append(
            {
                "type": "T4",
                "fields": {
                    "employment_income": _extract_amount(text, "Employment income"),
                },
            }
        )

    if "Interest from Canadian sources" in text or "eligible dividends" in text:
        slips.append(
            {
                "type": "T5",
                "fields": {
                    "interest_income": _extract_amount(text, "Interest from Canadian sources"),
                    "dividends": _extract_amount(text, "eligible dividends"),
                },
            }
        )

    if "RRSP contributions" in text:
        slips.append(
            {
                "type": "RRSP",
                "fields": {
                    "rrsp_contributions": _extract_amount(text, "RRSP contributions"),
                },
            }
        )

    return {"slips": slips}


def test_pipeline_end_to_end_uses_synthetic_fixture(monkeypatch):
    fixture_path = Path(__file__).resolve().parents[1] / "fixtures" / "slips" / "synthetic_full_case.txt"
    raw_doc = fixture_path.read_bytes()

    monkeypatch.setattr(parse_docs, "ocr_bytes_to_text", lambda doc, _mime: doc.decode("utf-8"))
    monkeypatch.setattr(parse_docs, "llm_parse", _mock_llm_parse)
    monkeypatch.setattr(
        explain_return,
        "client",
        _Client('{"lines": {"total_income": "from parsed slips", "taxable_income": "after RRSP deduction"}}'),
    )

    compiled = graph.build_graph()
    output = compiled.invoke(GraphState(raw_docs=[raw_doc]))
    final_state = GraphState.model_validate(output)

    assert final_state.draft_return is not None
    assert final_state.draft_return.total_income == pytest.approx(81700.5)
    assert final_state.draft_return.rrsp_deduction == pytest.approx(7000.0)
    assert final_state.draft_return.taxable_income == pytest.approx(74700.5)
    assert final_state.draft_return.estimated_tax == pytest.approx(18675.125)
    assert final_state.explanation is not None
    assert "total_income" in final_state.explanation.lines


def test_pipeline_handles_many_uploaded_docs(monkeypatch):
    fixture_path = Path(__file__).resolve().parents[1] / "fixtures" / "slips" / "synthetic_full_case.txt"
    raw_doc = fixture_path.read_bytes()
    docs = [raw_doc for _ in range(10)]

    monkeypatch.setattr(parse_docs, "ocr_bytes_to_text", lambda doc, _mime: doc.decode("utf-8"))
    monkeypatch.setattr(parse_docs, "llm_parse", _mock_llm_parse)
    monkeypatch.setattr(
        explain_return,
        "client",
        _Client('{"lines": {"total_income": "from parsed slips", "taxable_income": "after RRSP deduction"}}'),
    )

    compiled = graph.build_graph()
    output = compiled.invoke(GraphState(raw_docs=docs))
    final_state = GraphState.model_validate(output)

    assert final_state.draft_return is not None
    assert final_state.draft_return.total_income == pytest.approx(81700.5 * 10)
    assert final_state.draft_return.rrsp_deduction == pytest.approx(7000.0 * 10)
    assert final_state.draft_return.taxable_income == pytest.approx(74700.5 * 10)
    assert final_state.draft_return.estimated_tax == pytest.approx(18675.125 * 10)
