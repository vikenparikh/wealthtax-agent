"""Unit tests for the Claude CLI LLM wrapper (services/claude_llm.py).

Covers the pure helpers (_try_parse_json, _resolve_binary), the offline
StubLLM, and the ClaudeCLILLM subprocess paths (validate / complete /
complete_json) with subprocess.run mocked — no real `claude` binary needed.
"""

from types import SimpleNamespace

import pytest

import wealthtax_agent.services.claude_llm as claude_llm
from wealthtax_agent.services.claude_llm import (
    ClaudeCLILLM,
    LLMError,
    LLMResponse,
    StubLLM,
    _resolve_binary,
    _try_parse_json,
)


# --- _try_parse_json ---------------------------------------------------------


def test_try_parse_json_plain_object():
    assert _try_parse_json('{"a": 1}') == {"a": 1}


def test_try_parse_json_extracts_object_embedded_in_prose():
    assert _try_parse_json('Sure! {"tax_year": 2024} hope that helps') == {"tax_year": 2024}


def test_try_parse_json_returns_none_for_prose_without_json():
    assert _try_parse_json("no json here") is None


def test_try_parse_json_returns_none_for_empty_string():
    assert _try_parse_json("") is None


def test_try_parse_json_returns_none_for_brace_garbage():
    assert _try_parse_json("{not valid json}") is None


# --- _resolve_binary ---------------------------------------------------------


def test_resolve_binary_explicit_found_on_path(monkeypatch):
    monkeypatch.setattr(claude_llm.shutil, "which", lambda x: "/usr/bin/claude")
    assert _resolve_binary("claude") == "claude"


def test_resolve_binary_explicit_missing_returns_none(monkeypatch):
    monkeypatch.setattr(claude_llm.shutil, "which", lambda x: None)
    monkeypatch.setattr(claude_llm.Path, "exists", lambda self: False)
    assert _resolve_binary("/no/such/claude") is None


def test_resolve_binary_reads_env_var(monkeypatch):
    monkeypatch.setenv("CLAUDE_CLI_BIN", "/opt/claude")
    monkeypatch.setattr(claude_llm.shutil, "which", lambda x: x if x == "/opt/claude" else None)
    monkeypatch.setattr(claude_llm.Path, "exists", lambda self: False)
    assert _resolve_binary() == "/opt/claude"


def test_resolve_binary_none_when_nothing_found(monkeypatch):
    monkeypatch.delenv("CLAUDE_CLI_BIN", raising=False)
    monkeypatch.setattr(claude_llm.shutil, "which", lambda x: None)
    monkeypatch.setattr(claude_llm.Path, "exists", lambda self: False)
    assert _resolve_binary() is None


# --- StubLLM + LLMResponse ---------------------------------------------------


def test_stub_llm_matches_needle_and_records_calls():
    stub = StubLLM({"wash-sale": {"answer": "30 days"}})
    resp = stub.complete("Explain the wash-sale rule", schema_hint='{"answer":""}')
    assert resp.json == {"answer": "30 days"}
    assert stub.calls == [("Explain the wash-sale rule", '{"answer":""}')]


def test_stub_llm_returns_empty_when_no_match():
    resp = StubLLM().complete("anything")
    assert resp.json == {} and resp.text == "{}"


def test_stub_llm_complete_json_uses_default_when_empty():
    assert StubLLM().complete_json("x", '{"k":0}', default={"k": 5}) == {"k": 5}


def test_stub_llm_complete_json_returns_payload_on_match():
    stub = StubLLM({"year": {"tax_year": 2024}})
    assert stub.complete_json("what year", '{"tax_year":0}') == {"tax_year": 2024}


def test_llm_response_json_defaults_to_none():
    r = LLMResponse(text="hi")
    assert r.text == "hi" and r.json is None


# --- ClaudeCLILLM (subprocess mocked) ----------------------------------------


@pytest.fixture
def fake_run(monkeypatch):
    state = SimpleNamespace(
        version=SimpleNamespace(returncode=0, stdout="claude 1.2.3", stderr=""),
        completion=SimpleNamespace(returncode=0, stdout='{"tax_year": 2024}', stderr=""),
        raise_exc=None,
        commands=[],
    )

    def _run(cmd, **kwargs):
        state.commands.append(cmd)
        if "--version" in cmd:
            return state.version
        if state.raise_exc is not None:
            raise state.raise_exc
        return state.completion

    monkeypatch.setattr(claude_llm.shutil, "which", lambda x: "/usr/bin/claude")
    monkeypatch.setattr(claude_llm.subprocess, "run", _run)
    return state


def test_cli_validate_sets_available_and_version(fake_run):
    llm = ClaudeCLILLM(binary="claude")
    assert llm.available is True
    assert llm.claude_version == "claude 1.2.3"


def test_cli_validate_raises_when_binary_missing(monkeypatch):
    monkeypatch.setattr(claude_llm.shutil, "which", lambda x: None)
    monkeypatch.setattr(claude_llm.Path, "exists", lambda self: False)

    def _run(cmd, **kw):
        raise FileNotFoundError("no claude")

    monkeypatch.setattr(claude_llm.subprocess, "run", _run)
    with pytest.raises(RuntimeError, match="claude binary not found"):
        ClaudeCLILLM()


def test_cli_complete_parses_json_with_schema_hint(fake_run):
    llm = ClaudeCLILLM(binary="claude")
    resp = llm.complete("Extract year", schema_hint='{"tax_year": 0}')
    assert resp.text == '{"tax_year": 2024}'
    assert resp.json == {"tax_year": 2024}
    last = fake_run.commands[-1]
    assert "-p" in last and "--model" in last


def test_cli_complete_without_schema_hint_leaves_json_none(fake_run):
    resp = ClaudeCLILLM(binary="claude").complete("just chat")
    assert resp.json is None


def test_cli_complete_raises_llmerror_on_nonzero_exit(fake_run):
    fake_run.completion = SimpleNamespace(returncode=2, stdout="", stderr="boom")
    llm = ClaudeCLILLM(binary="claude")
    with pytest.raises(LLMError, match="exit=2"):
        llm.complete("x")


def test_cli_complete_raises_llmerror_on_timeout(fake_run):
    llm = ClaudeCLILLM(binary="claude")
    fake_run.raise_exc = claude_llm.subprocess.TimeoutExpired("claude", 1)
    with pytest.raises(LLMError, match="invocation failed"):
        llm.complete("x")


def test_cli_complete_json_returns_default_on_llmerror(fake_run):
    fake_run.completion = SimpleNamespace(returncode=1, stdout="", stderr="err")
    llm = ClaudeCLILLM(binary="claude")
    assert llm.complete_json("x", '{"k":0}', default={"k": 9}) == {"k": 9}


def test_get_tax_llm_is_cached(fake_run):
    claude_llm.get_tax_llm.cache_clear()
    try:
        assert claude_llm.get_tax_llm() is claude_llm.get_tax_llm()
    finally:
        claude_llm.get_tax_llm.cache_clear()


# --- complete() guard when not available (line 169) --------------------------


def test_cli_complete_raises_when_not_available(fake_run):
    """complete() must refuse to shell out if validate() never marked the
    instance available — the binary-not-found guard at the top of complete()."""
    llm = ClaudeCLILLM(binary="claude")
    llm.available = False
    with pytest.raises(LLMError, match="claude CLI binary not found"):
        llm.complete("anything")


# --- complete_json() return paths (lines 209-212) ----------------------------


def test_cli_complete_json_returns_parsed_json_on_success(fake_run):
    """When the completion parses to JSON, complete_json returns that dict (209-210)."""
    llm = ClaudeCLILLM(binary="claude")
    out = llm.complete_json("Extract year", '{"tax_year": 0}', default={"k": 1})
    assert out == {"tax_year": 2024}


def test_cli_complete_json_falls_back_to_default_when_json_unparseable(fake_run):
    """When the completion has no parseable JSON, complete_json returns the
    provided default (211-212) rather than the {"raw": ...} fallback."""
    fake_run.completion = SimpleNamespace(returncode=0, stdout="no json here", stderr="")
    llm = ClaudeCLILLM(binary="claude")
    out = llm.complete_json("chat", '{"k": 0}', default={"k": 7})
    assert out == {"k": 7}


def test_cli_complete_json_raw_fallback_when_no_default(fake_run):
    """With no default and unparseable output, complete_json wraps the raw text
    under a "raw" key (line 212 default branch)."""
    fake_run.completion = SimpleNamespace(returncode=0, stdout="just prose", stderr="")
    llm = ClaudeCLILLM(binary="claude")
    out = llm.complete_json("chat", '{"k": 0}')
    assert out == {"raw": "just prose"}
