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


@pytest.mark.parametrize("extension", ["pdf", "png", "jpg", "jpeg"])
def test_pipeline_supports_all_upload_file_formats(monkeypatch, extension):
    project_root = Path(__file__).resolve().parents[2]
    samples = project_root / "sample_tax_slips"

    t4_path = samples / f"t4_sample_2025.{extension}"
    t5_path = samples / f"t5_sample_2025.{extension}"
    rrsp_path = samples / f"rrsp_receipt_2025.{extension}"

    if t4_path.exists() and t5_path.exists() and rrsp_path.exists():
        t4_bytes = t4_path.read_bytes()
        t5_bytes = t5_path.read_bytes()
        rrsp_bytes = rrsp_path.read_bytes()
    else:
        t4_bytes = f"t4-{extension}".encode("utf-8")
        t5_bytes = f"t5-{extension}".encode("utf-8")
        rrsp_bytes = f"rrsp-{extension}".encode("utf-8")

    lookup = {
        t4_bytes: "Employment income (Box 14): 84500.00",
        t5_bytes: "Interest from Canadian sources (Box 13): 1325.40\nTaxable amount of eligible dividends (Box 24): 620.00",
        rrsp_bytes: "Total RRSP contributions: 9000.00",
    }

    monkeypatch.setattr(parse_docs, "ocr_bytes_to_text", lambda doc, _mime: lookup[doc])
    monkeypatch.setattr(parse_docs, "client", None)
    monkeypatch.setattr(
        explain_return,
        "client",
        _Client('{"lines": {"total_income": "from parsed slips", "estimated_tax": "simplified estimate"}}'),
    )

    compiled = graph.build_graph()
    output = compiled.invoke(GraphState(raw_docs=[t4_bytes, t5_bytes, rrsp_bytes]))
    final_state = GraphState.model_validate(output)

    assert final_state.draft_return is not None
    assert final_state.draft_return.total_income == pytest.approx(86445.4)
    assert final_state.draft_return.rrsp_deduction == pytest.approx(9000.0)
    assert final_state.draft_return.taxable_income == pytest.approx(77445.4)
    assert final_state.draft_return.estimated_tax == pytest.approx(19361.35)
    assert final_state.explanation is not None
