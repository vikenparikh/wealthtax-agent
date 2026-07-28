"""Coverage for the fallback / degradation branches of ``explain_return``.

These exercise the pure helpers (``_try_parse_explanation_lines``,
``_build_dual_output_fallback``) and the early-return / regex-fallback paths of
``generate_dual_outputs`` that the broader node tests don't reach. They assert
real output, not just that the call didn't raise.
"""

import json

import pytest

import wealthtax_agent.explain_return as explain_return
from wealthtax_agent.state import DraftReturn, Explanation, GraphState


# ---------------------------------------------------------------------------
# Test doubles (mirrors the style in test_explain_return_node.py)
# ---------------------------------------------------------------------------
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


def _draft() -> DraftReturn:
    return DraftReturn(
        total_income=100.0,
        rrsp_deduction=10.0,
        taxable_income=90.0,
        estimated_tax=22.5,
        estimated_refund=0.0,
    )


# ---------------------------------------------------------------------------
# _try_parse_explanation_lines — top-level known-keys branch (lines 97-100)
# ---------------------------------------------------------------------------
def test_parse_lines_from_top_level_known_keys_all_present():
    # dict WITHOUT a "lines" key but WITH all four known keys, all non-None.
    content = json.dumps(
        {
            "total_income": 100,
            "rrsp_deduction": 10,
            "taxable_income": 90,
            "estimated_tax": 22.5,
        }
    )

    result = explain_return._try_parse_explanation_lines(content)

    assert result == {
        "total_income": "100",
        "rrsp_deduction": "10",
        "taxable_income": "90",
        "estimated_tax": "22.5",
    }
    # every value is stringified
    assert all(isinstance(v, str) for v in result.values())


def test_parse_lines_top_level_known_key_none_falls_through():
    # One known key present but None -> the `all(... is not None)` guard fails,
    # so this branch does NOT return; it falls through to the line-parser, which
    # finds nothing (JSON has no `key: value` text lines) -> empty dict.
    content = json.dumps(
        {
            "total_income": 100,
            "rrsp_deduction": None,
            "taxable_income": 90,
            "estimated_tax": 22.5,
        }
    )

    result = explain_return._try_parse_explanation_lines(content)

    assert result == {}


# ---------------------------------------------------------------------------
# _try_parse_explanation_lines — plain-text line parser (lines 106-109)
# ---------------------------------------------------------------------------
def test_parse_lines_from_plain_text_colon_lines():
    content = (
        "total_income: 123\n"
        "Rrsp Deduction: 45\n"          # normalized: lowercase + spaces -> underscore
        "unknown_key: 999\n"            # unknown normalized key -> ignored
        "this line has no colon\n"      # no ':' -> skipped
        "estimated_tax:   \n"           # known key but empty value -> skipped
    )

    result = explain_return._try_parse_explanation_lines(content)

    assert result == {
        "total_income": "123",
        "rrsp_deduction": "45",
    }
    assert "unknown_key" not in result
    assert "estimated_tax" not in result


# ---------------------------------------------------------------------------
# _build_dual_output_fallback — missing draft (line 125)
# ---------------------------------------------------------------------------
def test_build_fallback_raises_when_draft_missing():
    state = GraphState()  # draft_return is None

    with pytest.raises(ValueError, match="Draft return missing"):
        explain_return._build_dual_output_fallback(state)


# ---------------------------------------------------------------------------
# _build_dual_output_fallback — default explanation lines (line 132)
# ---------------------------------------------------------------------------
def test_build_fallback_uses_default_lines_when_no_explanation():
    state = GraphState(draft_return=_draft())  # explanation is None -> {} -> defaults

    summary_text, pseudo_xml = explain_return._build_dual_output_fallback(state)

    # A default phrase (only present in the hardcoded default lines) must appear.
    assert "Derived from detected RRSP contribution receipts." in summary_text
    assert "Simplified estimate for prototype use only." in summary_text
    # Dollar formatting from the fallback still emits.
    assert "Total income: $100.00" in summary_text
    assert pseudo_xml.startswith("<WealthTaxDraftReturn>")


def test_build_fallback_uses_provided_explanation_lines():
    # Contrast case: explanation present -> its lines are used, NOT the defaults.
    state = GraphState(
        draft_return=_draft(),
        explanation=Explanation(lines={"total_income": "custom line here"}),
    )

    summary_text, _ = explain_return._build_dual_output_fallback(state)

    assert "- total_income: custom line here" in summary_text
    assert "Derived from detected RRSP contribution receipts." not in summary_text


# ---------------------------------------------------------------------------
# generate_dual_outputs — early return when no draft (line 178)
# ---------------------------------------------------------------------------
def test_generate_dual_outputs_returns_unchanged_when_no_draft(monkeypatch):
    # The `draft_return is None` guard is the FIRST statement in
    # generate_dual_outputs, so it returns before the function ever resolves a
    # client via `_get_client()`. Patching the module-global `client` with an
    # exploding stub is belt-and-suspenders: if the guard regressed and any
    # client path ran, `.create()` would raise and fail this test loudly.
    class _ExplodingClient:
        class _Chat:
            class _Completions:
                def create(self, **kwargs):  # pragma: no cover - must not run
                    raise AssertionError("client must not be called when draft is None")

            completions = _Completions()

        chat = _Chat()

    monkeypatch.setattr(explain_return, "client", _ExplodingClient())

    state = GraphState()  # draft_return is None
    result = explain_return.generate_dual_outputs(state)

    assert result is state
    assert result.draft_summary_text is None
    assert result.draft_pseudo_xml is None
    assert result.warnings == []


# ---------------------------------------------------------------------------
# generate_dual_outputs — text-code-block regex fallback branch (line 207)
# ---------------------------------------------------------------------------
@pytest.mark.skip(
    reason=(
        "Line 207 is unreachable. The inner fallback regex "
        'r"```text\\\\s*(.*?)```" (literal backslash + `s*`) is STRICTLY '
        'NARROWER than the primary extractor regex rf"```{language}\\s*(.*?)```" '
        "(a real \\s whitespace class). Any content that matches the fallback "
        "also matches the primary, so `_extract_code_block(content, 'text')` "
        "never raises in the case where `match` would be truthy — the fallback's "
        "`if match:` true-branch cannot execute. Covering it would require "
        "mocking `_extract_code_block` itself, which the task says not to force."
    )
)
def test_generate_dual_outputs_regex_text_fallback():
    pass
