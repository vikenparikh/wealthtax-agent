"""Rung-3 security: user-rendered warnings/notes from build_return must scrub PII.

The four ``except`` blocks in build_return.py interpolate ``str(exc)`` from the
DraftReturn -> filing-artifact serializers (which process the user's tax data)
into ``state.warnings`` / planning-projection notes. A serializer exception can
embed an SSN/SIN/PAN-shaped value, leaking PII to the user. Every such site must
run the raw exception text through ``sanitize_runtime_error`` first.
"""

import base64

import wealthtax_agent.build_return as br
from wealthtax_agent.build_return import build_return_node
from wealthtax_agent.state import DraftReturn, GraphState

_SSN = "123-45-6789"  # synthetic SSN-shaped value


def _state(drafts, **kw):
    return GraphState(filing_year=2024, draft_returns=drafts, **kw)


def _decode(artifact) -> str:
    return base64.b64decode(artifact.content_b64).decode("utf-8")


def test_jurisdiction_failure_warning_redacts_ssn(monkeypatch):
    def _boom(*a, **k):
        raise ValueError(f"boom {_SSN}")

    monkeypatch.setattr(br, "_ca_artifacts", _boom)
    out = build_return_node(_state({"CA": DraftReturn(jurisdiction="CA", totals={"total_income": 80000})}))
    warn = next(w for w in out.warnings if "Filing artifact generation failed for CA" in w)
    assert _SSN not in warn
    assert "[REDACTED]" in warn


def test_yoy_planning_failure_warning_redacts_ssn(monkeypatch):
    def _boom(*a, **k):
        raise ValueError(f"plan boom {_SSN}")

    monkeypatch.setattr(br, "_planning_artifact", _boom)
    out = build_return_node(_state({"CA": DraftReturn(jurisdiction="CA", totals={"total_income": 80000})}))
    warn = next(w for w in out.warnings if "YoY planning artifact failed" in w)
    assert _SSN not in warn
    assert "[REDACTED]" in warn


def test_amendment_failure_warning_redacts_ssn(monkeypatch):
    def _boom(*a, **k):
        raise ValueError(f"adj boom {_SSN}")

    monkeypatch.setattr(br, "_amendment_artifacts", _boom)
    state = _state(
        {"US": DraftReturn(jurisdiction="US", totals={"total_tax": 11000})},
        is_amendment=True,
        prior_filed_totals={"US": {"total_tax": 9000}},
    )
    out = build_return_node(state)
    warn = next(w for w in out.warnings if "Amendment artifact failed" in w)
    assert _SSN not in warn
    assert "[REDACTED]" in warn


def test_projection_unavailable_note_redacts_ssn(monkeypatch):
    # The projection note is embedded inside the YoY planning artifact text.
    import wealthtax_agent.build_return as mod

    def _boom(*a, **k):
        raise ValueError(f"projection boom {_SSN}")

    monkeypatch.setattr(mod, "project_future_years", _boom)
    out = build_return_node(_state({"CA": DraftReturn(jurisdiction="CA", totals={"total_income": 80000})}))
    text = _decode(out.filing_artifacts["yoy_planning"])
    assert "projection unavailable" in text
    assert _SSN not in text
    assert "[REDACTED]" in text


def test_normal_error_text_remains_readable(monkeypatch):
    # No PII -> message passes through unchanged (sanitizer is a no-op on clean text).
    def _boom(*a, **k):
        raise RuntimeError("us serialize failed")

    monkeypatch.setattr(br, "_us_artifacts", _boom)
    out = build_return_node(_state({"US": DraftReturn(jurisdiction="US", totals={"total_tax": 9000})}))
    assert any("Filing artifact generation failed for US: us serialize failed" in w for w in out.warnings)
