"""Regression: generate_dual_outputs must not write a debug file to cwd.

The format-output fallback branches previously wrote the RAW LLM response to a
relative-path file `format_llm_response_debug.txt` in the current working
directory. That is a PII-at-rest leak (raw content holds the user's tax
figures, unencrypted) and clobbers a tracked repo file. These tests pin that
no such file is created in either fallback branch, while the fallback text is
still produced.
"""

import wealthtax_agent.explain_return as explain_return
from wealthtax_agent.state import DraftReturn, GraphState


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
    def __init__(self, output):
        self.output = output

    def create(self, **kwargs):
        return _Resp(self.output)


class _Chat:
    def __init__(self, output):
        self.completions = _Completions(output)


class _Client:
    def __init__(self, output):
        self.chat = _Chat(output)


def _state():
    return GraphState(
        draft_return=DraftReturn(
            total_income=100.0,
            rrsp_deduction=10.0,
            taxable_income=90.0,
            estimated_tax=22.5,
            estimated_refund=0.0,
        ),
        explanation=explain_return.Explanation(lines={"total_income": "ok"}),
    )


def test_missing_text_block_fallback_writes_no_debug_file(monkeypatch, tmp_path):
    # Branch (i): _extract_code_block(content, "text") raises -> inner except.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(explain_return, "client", _Client("no code blocks here"))

    result = explain_return.generate_dual_outputs(_state())

    assert not (tmp_path / "format_llm_response_debug.txt").exists()
    assert result.draft_summary_text
    assert result.draft_pseudo_xml is not None
    assert any("Output formatting fallback used:" in w for w in result.warnings)


def test_outer_exception_fallback_writes_no_debug_file(monkeypatch, tmp_path):
    # Branch (ii): call_with_retry raises -> outer except.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(explain_return, "client", _Client("anything"))

    def _boom(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(explain_return, "call_with_retry", _boom)

    result = explain_return.generate_dual_outputs(_state())

    assert not (tmp_path / "format_llm_response_debug.txt").exists()
    assert result.draft_summary_text
    assert result.draft_pseudo_xml is not None
    assert any("Output formatting fallback used:" in w for w in result.warnings)
