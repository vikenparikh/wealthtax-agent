"""P2-AC8 — structured (JSON) logging with PII redaction.

Pins:

* Every log record emitted by ``wealthtax_agent.llm``,
  ``wealthtax_agent.graph``, and ``wealthtax_agent.build_return`` is a single
  line of valid JSON (parseable with ``json.loads``).
* No record contains an SSN-shaped (``\\b\\d{3}-\\d{2}-\\d{4}\\b``),
  SIN-shaped (``\\b\\d{9}\\b``), or PAN-shaped
  (``\\b[A-Z]{5}\\d{4}[A-Z]\\b``) substring — the JSON formatter scrubs them
  before serialisation.

Tests exercise the three modules at their existing emission points (retry
warnings, graph construction, build-return start) so we aren't asserting on
a hypothetical logger.
"""

from __future__ import annotations

import io
import json
import logging
import re
from typing import List

import pytest

from wealthtax_agent.logging_utils import (
    JSONFormatter,
    get_logger,
    reset_loggers,
    scrub_pii,
)


_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_SIN_RE = re.compile(r"\b\d{9}\b")
_PAN_RE = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")


def _no_pii(text: str) -> None:
    """Assert that ``text`` does not contain SSN/SIN/PAN-shaped substrings."""
    assert not _SSN_RE.search(text), f"SSN-shaped substring leaked: {text!r}"
    assert not _PAN_RE.search(text), f"PAN-shaped substring leaked: {text!r}"
    assert not _SIN_RE.search(text), f"SIN-shaped substring leaked: {text!r}"


def _attach_capture(logger_name: str) -> io.StringIO:
    """Replace a module logger's handler with one that writes to StringIO."""
    reset_loggers([logger_name])
    buf = io.StringIO()
    logger = get_logger(logger_name, stream=buf)
    # get_logger is idempotent — confirm our buf is what's attached.
    assert logger.handlers, f"logger {logger_name} has no handlers after setup"
    return buf


def _lines(buf: io.StringIO) -> List[str]:
    return [line for line in buf.getvalue().splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Unit-level checks on the formatter + scrubber.
# ---------------------------------------------------------------------------
def test_scrub_pii_redacts_ssn_sin_pan() -> None:
    raw = "SSN 123-45-6789 SIN 987654321 PAN ABCDE1234F end"
    out = scrub_pii(raw)
    _no_pii(out)
    assert "REDACTED" in out


def test_scrub_pii_walks_nested_containers() -> None:
    payload = {"ssn": "111-22-3333", "kids": ["AAAAA1111Z", {"sin": "123456789"}]}
    out = scrub_pii(payload)
    _no_pii(json.dumps(out))
    assert out["ssn"] == "[REDACTED]"
    assert out["kids"][0] == "[REDACTED]"
    assert out["kids"][1]["sin"] == "[REDACTED]"


def test_scrub_pii_leaves_non_pii_alone() -> None:
    assert scrub_pii("hello world") == "hello world"
    assert scrub_pii(42) == 42
    assert scrub_pii(None) is None
    # 8-digit (not 9) numbers must NOT be scrubbed.
    assert scrub_pii("order 12345678 confirmed") == "order 12345678 confirmed"


def test_formatter_emits_valid_json_with_extras() -> None:
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    record.user_id = "u-1"
    record.taxpayer_ssn = "111-22-3333"  # PII passthrough must be scrubbed
    payload = json.loads(formatter.format(record))
    assert payload["msg"] == "hello"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "test"
    assert payload["user_id"] == "u-1"
    assert payload["taxpayer_ssn"] == "[REDACTED]"


def test_formatter_handles_exc_info() -> None:
    formatter = JSONFormatter()
    try:
        raise RuntimeError("kaboom — SIN 987654321 in msg")
    except RuntimeError:
        import sys

        record = logging.LogRecord(
            name="test", level=logging.ERROR, pathname=__file__, lineno=1,
            msg="oops", args=(), exc_info=sys.exc_info(),
        )
    payload = json.loads(formatter.format(record))
    assert "exc" in payload
    _no_pii(payload["exc"])


# ---------------------------------------------------------------------------
# llm.py — retry warning emits JSON, scrubs PII.
# ---------------------------------------------------------------------------
def test_llm_call_with_retry_emits_valid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    buf = _attach_capture("wealthtax_agent.llm")
    from wealthtax_agent import llm

    # Patch sleep so retries don't actually wait.
    monkeypatch.setattr(llm.time, "sleep", lambda _: None)

    def boom() -> None:
        # Embed PII-shaped tokens in the exception message to exercise the scrubber.
        raise RuntimeError("rate limit hit for SSN 111-22-3333 and PAN ABCDE1234F")

    with pytest.raises(RuntimeError):
        llm.call_with_retry(boom, max_attempts=2, base_delay_seconds=0)

    lines = _lines(buf)
    assert lines, "llm logger emitted no records"
    for line in lines:
        payload = json.loads(line)
        assert payload["level"] == "WARNING"
        assert payload["logger"] == "wealthtax_agent.llm"
        _no_pii(line)


# ---------------------------------------------------------------------------
# graph.py — build_graph + build_legacy_graph emit valid JSON.
# ---------------------------------------------------------------------------
def test_graph_build_emits_valid_json() -> None:
    buf = _attach_capture("wealthtax_agent.graph")
    from wealthtax_agent import graph

    graph.build_graph()
    graph.build_legacy_graph()

    lines = _lines(buf)
    assert len(lines) >= 2, f"expected at least 2 records, got {lines}"
    variants = set()
    for line in lines:
        payload = json.loads(line)
        assert payload["logger"] == "wealthtax_agent.graph"
        assert payload["msg"] == "graph_build_start"
        variants.add(payload.get("variant"))
        _no_pii(line)
    assert {"full", "legacy"}.issubset(variants)


# ---------------------------------------------------------------------------
# build_return.py — emission survives PII-shaped jurisdiction tokens.
# ---------------------------------------------------------------------------
def test_build_return_emits_valid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    buf = _attach_capture("wealthtax_agent.build_return")
    from wealthtax_agent import build_return as br
    from wealthtax_agent.state import GraphState

    # Empty state — no draft returns means no per-jurisdiction work, but the
    # start log should still fire, proving the emission path is hooked.
    state = GraphState(filing_year=2024)
    br.build_return_node(state)

    lines = _lines(buf)
    assert lines, "build_return logger emitted no records"
    payload = json.loads(lines[0])
    assert payload["logger"] == "wealthtax_agent.build_return"
    assert payload["msg"] == "build_return_start"
    assert payload["year"] == 2024
    for line in lines:
        _no_pii(line)


def test_build_return_logs_failure_when_artifact_generation_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    buf = _attach_capture("wealthtax_agent.build_return")
    from wealthtax_agent import build_return as br
    from wealthtax_agent.state import DraftReturn, GraphState

    # Force the CA branch to raise so the error-logging branch is exercised.
    def _explode(*args, **kwargs):
        raise RuntimeError("artifact boom SSN 222-33-4444")

    monkeypatch.setattr(br, "_ca_artifacts", _explode)

    state = GraphState(filing_year=2024)
    state.draft_returns["CA"] = DraftReturn(
        jurisdiction="CA",
        tax_year=2024,
        total_income=0.0,
        rrsp_deduction=0.0,
        taxable_income=0.0,
        estimated_tax=0.0,
        estimated_refund=0.0,
    )
    br.build_return_node(state)

    lines = _lines(buf)
    error_lines = [json.loads(l) for l in lines if json.loads(l)["level"] == "ERROR"]
    assert error_lines, f"no ERROR record emitted; got {lines}"
    assert error_lines[0]["msg"] == "build_return_failed"
    assert error_lines[0]["jurisdiction"] == "CA"
    for line in lines:
        _no_pii(line)


# ---------------------------------------------------------------------------
# Integration: every record across all three loggers is parseable JSON.
# ---------------------------------------------------------------------------
def test_all_three_loggers_emit_parseable_json(monkeypatch: pytest.MonkeyPatch) -> None:
    llm_buf = _attach_capture("wealthtax_agent.llm")
    graph_buf = _attach_capture("wealthtax_agent.graph")
    br_buf = _attach_capture("wealthtax_agent.build_return")

    from wealthtax_agent import build_return as br
    from wealthtax_agent import graph as g
    from wealthtax_agent import llm
    from wealthtax_agent.state import GraphState

    monkeypatch.setattr(llm.time, "sleep", lambda _: None)
    with pytest.raises(RuntimeError):
        llm.call_with_retry(
            lambda: (_ for _ in ()).throw(RuntimeError("429 rate limit SIN 123456789")),
            max_attempts=2,
            base_delay_seconds=0,
        )
    g.build_graph()
    br.build_return_node(GraphState(filing_year=2024))

    all_lines = _lines(llm_buf) + _lines(graph_buf) + _lines(br_buf)
    assert len(all_lines) >= 3, f"expected ≥3 records across 3 loggers, got {all_lines}"
    for line in all_lines:
        payload = json.loads(line)  # must be valid JSON
        assert "msg" in payload and "level" in payload and "logger" in payload
        _no_pii(line)


def teardown_module(module) -> None:  # noqa: ARG001 — pytest hook signature
    """Drop our captured-stream handlers so other tests aren't affected."""
    reset_loggers([
        "wealthtax_agent.llm",
        "wealthtax_agent.graph",
        "wealthtax_agent.build_return",
    ])
