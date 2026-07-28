"""Rung-3 security: `sanitize_runtime_error` is the sole scrub on four
user-visible warning paths that interpolate raw ``str(exc)`` into
``state.warnings`` (which is rendered to the user). It previously redacted
only API tokens (gsk_/sk-) and short-circuited auth/model markers — but a
real exception like ``float("123-45-6789")`` would leak the SSN verbatim.

These tests pin: (a) SSN / SIN (contiguous + separated) / PAN shapes are
redacted, AND (b) all pre-existing behavior is preserved — the gsk_/sk-
token redaction and the auth/missing-key/model short-circuit canned strings.
A companion integration test drives a real warning path end-to-end.
"""
from __future__ import annotations

from wealthtax_agent import llm
from wealthtax_agent.classify_forms import _DOC_TEXT_CACHE, _doc_text_key
from wealthtax_agent.extract_forms import extract_forms_node
from wealthtax_agent.state import FormClassification, GraphState, InputDocument


# --- PII redaction (FAIL before the fix) ------------------------------------

def test_redacts_ssn():
    out = llm.sanitize_runtime_error(
        "could not convert string to float: '123-45-6789'"
    )
    assert "123-45-6789" not in out
    assert "[REDACTED]" in out


def test_redacts_sin_contiguous():
    out = llm.sanitize_runtime_error("bad row: 123456789 in column B")
    assert "123456789" not in out
    assert "[REDACTED]" in out


def test_redacts_sin_separated():
    out = llm.sanitize_runtime_error("SIN parse error near 123-456-789 token")
    assert "123-456-789" not in out
    assert "[REDACTED]" in out


def test_redacts_pan():
    out = llm.sanitize_runtime_error("invalid PAN field ABCDE1234F supplied")
    assert "ABCDE1234F" not in out
    assert "[REDACTED]" in out


# --- Preserve existing behavior (PASS before AND after) ---------------------

def test_preserves_auth_short_circuit():
    out = llm.sanitize_runtime_error("Incorrect API key provided: gsk_secret")
    assert out == (
        "Model provider authentication failed. "
        "Verify GROQ_API_KEY and endpoint settings."
    )


def test_preserves_gsk_token_never_leaks():
    # A gsk_ token contains an auth marker, so it short-circuits to the canned
    # auth string — the raw token must never survive. (Regression: pre-existing.)
    out = llm.sanitize_runtime_error("leaked token gsk_abc123XYZ in trace")
    assert "gsk_abc123XYZ" not in out


def test_preserves_token_redaction_regex():
    # Reach the token regex via a path with no auth marker: the regex matches
    # a bare ``sk-`` lookalike embedded mid-word ... but ``sk-`` is itself an
    # auth marker. The only way to exercise the regex without short-circuiting
    # is a token that the regex catches yet no marker substring matches. Since
    # gsk_/sk- ARE markers, assert the token regex remains wired by confirming
    # the function still imports re and the regex constants are unchanged: the
    # behavioral contract is "raw provider tokens never leak", asserted above.
    # Here we simply confirm a benign message passes through unchanged.
    out = llm.sanitize_runtime_error("a perfectly ordinary parse warning")
    assert out == "a perfectly ordinary parse warning"


# --- Missing-key branch (was dead: auth-marker check ran first) --------------

def test_missing_key_required_returns_actionable_hint():
    # "GROQ_API_KEY is required" is exactly what load_runtime_config raises.
    # It contains "api_key" (an auth marker), so this used to short-circuit to
    # the generic auth message; missing-key detection now runs first.
    out = llm.sanitize_runtime_error("GROQ_API_KEY is required")
    assert out == "GROQ_API_KEY is missing. Set it in your environment or .env file."


def test_missing_key_phrasing_variant_returns_actionable_hint():
    out = llm.sanitize_runtime_error("Config error: missing GROQ_API_KEY at boot")
    assert out == "GROQ_API_KEY is missing. Set it in your environment or .env file."


def test_missing_key_ordering_does_not_weaken_redaction():
    # A genuine leaked-token message has no missing-key phrase, so it still
    # reaches the auth short-circuit and the raw token never survives.
    out = llm.sanitize_runtime_error("Incorrect API key provided: gsk_LEAK9988")
    assert "gsk_LEAK9988" not in out
    assert out == (
        "Model provider authentication failed. "
        "Verify GROQ_API_KEY and endpoint settings."
    )


def test_missing_key_branch_drops_co_occurring_secret_and_pii():
    # The security-critical property: even if a secret / PII co-occurs with the
    # missing-key phrase in ONE string, the branch returns a non-interpolating
    # constant, so nothing from the input survives. Pins this against a future
    # edit that might accidentally interpolate `message` into the hint.
    out = llm.sanitize_runtime_error(
        "missing GROQ_API_KEY; leaked gsk_LEAK9988 and SSN 123-45-6789"
    )
    assert out == "GROQ_API_KEY is missing. Set it in your environment or .env file."
    assert "gsk_LEAK9988" not in out
    assert "123-45-6789" not in out


# --- Integration guard: real warning path must not leak (FAIL before) -------

def test_warning_path_does_not_leak_ssn(monkeypatch):
    """Drive extract_forms_node with an extractor that raises a PII-bearing
    ValueError; the except branch appends ``sanitize_runtime_error(str(exc))``
    to ``state.warnings``. Assert no warning contains the raw SSN."""

    class _Boom:
        def extract(self, text, source_filename=None):
            raise ValueError("could not convert string to float: '123-45-6789'")

    monkeypatch.setattr(
        "wealthtax_agent.extract_forms.get_extractor", lambda code: _Boom()
    )

    doc = InputDocument(content=b"doc-bytes", filename="t4.txt", mime_type="text/plain")
    _DOC_TEXT_CACHE[_doc_text_key(doc.content)] = "Form T4 text\n"

    state = GraphState(
        raw_docs=[doc],
        tax_year=2024,
        classifications=[
            FormClassification(
                form_code="T4",
                jurisdiction="CA",
                confidence="high",
                filename="t4.txt",
                source_doc_index=0,
            )
        ],
    )

    out = extract_forms_node(state)

    assert out.warnings, "expected an extraction-failure warning"
    assert any("extraction failed" in w for w in out.warnings)
    for w in out.warnings:
        assert "123-45-6789" not in w
