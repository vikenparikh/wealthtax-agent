"""Branch coverage for the Groq client wrapper (``llm.py``).

Existing tests cover the happy config path, the auth short-circuit, gsk_ token
redaction, retry-success, and dotenv reload/override. This file pins the
remaining error-messaging, retry-edge, and dotenv-parsing branches — the ones a
silent regression would degrade invisibly:

* ``sanitize_runtime_error`` — the decommissioned-model branch emits its
  specific operator message, and a plain message falls through the token
  regexes + PII scrub intact. (The missing-key branch is intentionally NOT
  tested: ``auth_markers`` contains ``"api_key"`` and is checked first, so
  every ``missing_key_markers`` string — all of which contain ``"api_key"`` —
  short-circuits to the auth message. Those lines are unreachable; see the PR
  note flagging that dead branch rather than papering over it with a test.)
* ``call_with_retry`` — a degenerate ``max_attempts`` never enters the loop, so
  ``last_error`` stays ``None`` and the helper must raise a clear RuntimeError
  rather than return ``None`` and let a caller dereference it.
* ``_load_dotenv_if_present`` — ``export KEY=val`` lines, comments/blanks, and
  malformed (no ``=``) lines must parse robustly, and an unchanged .env on a
  second load must short-circuit on the content fingerprint (no re-import).
* ``get_model`` rejects unknown kinds; the thin provider getters return config.

All test-only; no ``src/`` change. Non-money path (LLM transport plumbing).
"""

from __future__ import annotations

import importlib

import pytest

import wealthtax_agent.llm as llm


# --- sanitize_runtime_error branches ----------------------------------------


def test_sanitize_model_decommissioned_marker_returns_model_message():
    msg = llm.sanitize_runtime_error(
        "The model has been decommissioned and is no longer supported"
    )
    assert msg == (
        "Configured model is no longer supported. Update "
        "OCR_MODEL/PARSE_MODEL/EXPLAIN_MODEL to an active Groq model."
    )


def test_sanitize_plain_message_passes_through_scrubbed():
    # No marker, no token, no PII -> returned intact (exercises the tail return).
    assert llm.sanitize_runtime_error("temporary blip") == "temporary blip"


# --- call_with_retry degenerate path ----------------------------------------


def test_call_with_retry_zero_attempts_raises_runtime_error():
    calls = []

    def never_called():
        calls.append(1)
        return "unreachable"

    with pytest.raises(RuntimeError, match="Retry helper failed without an exception"):
        llm.call_with_retry(never_called, max_attempts=0)
    assert calls == []  # loop body never ran


def test_call_with_retry_reraises_last_error_after_exhausting_attempts():
    class Boom(Exception):
        pass

    def always_rate_limited():
        raise Boom("rate limit exceeded")  # retryable marker

    with pytest.raises(Boom):
        llm.call_with_retry(always_rate_limited, max_attempts=2, base_delay_seconds=0)


# --- _load_dotenv_if_present parsing branches --------------------------------


def _write_env(tmp_path, body):
    env = tmp_path / ".env"
    env.write_text(body)
    return env


def test_dotenv_parses_export_comment_and_malformed_lines(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WT_EXPORTED", raising=False)
    monkeypatch.delenv("WT_PLAIN", raising=False)
    _write_env(
        tmp_path,
        "\n".join(
            [
                "# a comment line",
                "",
                "export WT_EXPORTED=exported-value",
                'WT_PLAIN="quoted-value"',
                "MALFORMED_NO_EQUALS_LINE",
            ]
        ),
    )
    # Reset the module cache so this .env is actually (re)read.
    llm._DOTENV_CACHE.pop("fingerprint", None)
    llm._load_dotenv_if_present()

    import os

    assert os.environ["WT_EXPORTED"] == "exported-value"
    assert os.environ["WT_PLAIN"] == "quoted-value"


def test_dotenv_unchanged_content_short_circuits_on_fingerprint(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_env(tmp_path, "WT_FINGERPRINT_KEY=v1\n")
    llm._DOTENV_CACHE.pop("fingerprint", None)
    llm._load_dotenv_if_present()

    import os

    # Mutate the env in-process; an unchanged .env must NOT re-import over it.
    os.environ["WT_FINGERPRINT_KEY"] = "mutated"
    llm._load_dotenv_if_present()  # same content -> fingerprint hit -> no-op
    assert os.environ["WT_FINGERPRINT_KEY"] == "mutated"


# --- get_model / thin getters ------------------------------------------------


def test_get_model_rejects_unknown_kind(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test-key")
    with pytest.raises(ValueError, match="Unsupported model kind"):
        llm.get_model("nonsense")


def test_get_model_maps_known_kinds(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test-key")
    assert llm.get_model("ocr")
    assert llm.get_model("parse")
    assert llm.get_model("explain")


def test_thin_getters_return_runtime_values(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test-key")
    assert llm.get_base_url("groq")  # non-empty base url
    assert llm.get_api_key("groq") == "gsk-test-key"
    assert llm.get_provider_name() == "groq"


# --- provider detection guard ------------------------------------------------


def test_detect_provider_rejects_non_groq(monkeypatch):
    # Isolated to this test via monkeypatch (auto-reverted); never set process-wide.
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    with pytest.raises(ValueError, match="Only the 'groq' provider is supported"):
        llm._detect_provider()


def test_detect_provider_defaults_to_groq_when_unset(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert llm._detect_provider() == "groq"


# --- import-time fallback (defensive except branch) --------------------------


def test_import_time_fallback_when_config_unavailable(tmp_path, monkeypatch):
    """When config resolution raises at import (e.g. no GROQ_API_KEY), the module
    must still expose safe default model constants rather than fail to import.

    Hermetic: cwd is an empty tmp dir and there is no repo-root .env, so dotenv
    discovery finds nothing and the missing key propagates to the import-time
    ``except`` fallback. The ``finally`` reloads with a valid key so any later
    test importing ``llm`` fresh sees a normal module state.
    """
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.chdir(tmp_path)
    try:
        reloaded = importlib.reload(llm)
        assert reloaded.PROVIDER_NAME == "groq"
        assert reloaded.OCR_MODEL == "meta-llama/llama-4-scout-17b-16e-instruct"
        assert reloaded.PARSE_MODEL == "llama-3.1-8b-instant"
        assert reloaded.EXPLAIN_MODEL == "llama-3.1-8b-instant"
    finally:
        monkeypatch.setenv("GROQ_API_KEY", "gsk-test-key")
        importlib.reload(llm)
