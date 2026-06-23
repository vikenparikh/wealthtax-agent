"""Observability regression tests for the explain node.

The two broad ``except Exception`` sites in ``explain_return`` must keep their
graceful degradation (canned fallback, never abort the graph), but UNEXPECTED
programming errors (AttributeError/KeyError/TypeError/...) must be LOGGED LOUDLY
at ERROR level with a stack trace so a real bug is observable — instead of being
buried in the same sanitized one-line WARNING used for genuine LLM failures.

EXPECTED LLM/value failures (auth ValueError, ConnectionError, ...) keep the
quiet warning + fallback they have today.

Both paths still degrade gracefully: the node never raises, always returns a
populated state. Only the log VISIBILITY differs.
"""

import logging

import pytest

import wealthtax_agent.explain_return as explain_return
from wealthtax_agent.state import DraftReturn, Explanation, GraphState


_LOGGER_NAME = "wealthtax_agent.explain_return"


@pytest.fixture
def capture_explain_logs(caplog):
    """Attach pytest's capture handler to the module logger.

    ``get_logger`` sets ``propagate=False`` so records never reach the root
    logger where ``caplog`` listens by default. Attaching the capture handler
    directly to ``wealthtax_agent.explain_return`` lets us observe its records.
    """
    logger = logging.getLogger(_LOGGER_NAME)
    logger.addHandler(caplog.handler)
    previous_level = logger.level
    logger.setLevel(logging.DEBUG)
    try:
        yield caplog
    finally:
        logger.removeHandler(caplog.handler)
        logger.setLevel(previous_level)


def _draft_state() -> GraphState:
    return GraphState(
        draft_return=DraftReturn(
            total_income=100.0,
            rrsp_deduction=10.0,
            taxable_income=90.0,
            estimated_tax=22.5,
            estimated_refund=0.0,
        ),
        explanation=Explanation(lines={"total_income": "ok"}),
    )


class _RaisingCompletions:
    def __init__(self, exc):
        self._exc = exc

    def create(self, **kwargs):
        raise self._exc


class _RaisingChat:
    def __init__(self, exc):
        self.completions = _RaisingCompletions(exc)


class _RaisingClient:
    def __init__(self, exc):
        self.chat = _RaisingChat(exc)


def _error_records(caplog):
    return [r for r in caplog.records if r.levelno >= logging.ERROR]


# ---------------------------------------------------------------------------
# explain_return_node
# ---------------------------------------------------------------------------
def test_explain_node_logs_loudly_on_programming_error(monkeypatch, capture_explain_logs):
    caplog = capture_explain_logs
    monkeypatch.setattr(
        explain_return, "client", _RaisingClient(AttributeError("boom"))
    )
    state = _draft_state()

    result = explain_return.explain_return_node(state)

    # Graceful degrade: still returns a canned Explanation, never raises.
    assert result.explanation is not None
    assert "total_income" in result.explanation.lines

    # Loud + observable: an ERROR record carrying the AttributeError traceback.
    errors = _error_records(caplog)
    assert errors, "expected a loud ERROR-level log for the programming error"
    record = errors[0]
    assert record.exc_info is not None, "expected exc_info (stack trace) on the record"
    assert record.exc_info[0] is AttributeError
    assert "AttributeError" in (caplog.text or "")


def test_explain_node_quiet_on_real_llm_failure(monkeypatch, capture_explain_logs):
    caplog = capture_explain_logs
    monkeypatch.setattr(
        explain_return,
        "client",
        _RaisingClient(ValueError("api_key gsk-secret exposed")),
    )
    state = _draft_state()

    result = explain_return.explain_return_node(state)

    # Graceful degrade with the canned fallback.
    assert result.explanation is not None
    assert "total_income" in result.explanation.lines

    # Quiet: stays at WARNING, no ERROR-level loud log for an expected failure.
    assert not _error_records(caplog), "expected no ERROR log for an expected LLM failure"

    # Sensitive value stays redacted in the user-facing warning.
    assert any(
        "Model provider authentication failed. Verify GROQ_API_KEY and endpoint settings."
        in w
        for w in result.warnings
    )
    assert not any("gsk-secret" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# generate_dual_outputs
# ---------------------------------------------------------------------------
def test_generate_dual_outputs_logs_loudly_on_programming_error(monkeypatch, capture_explain_logs):
    caplog = capture_explain_logs
    monkeypatch.setattr(
        explain_return, "client", _RaisingClient(KeyError("missing_field"))
    )
    state = _draft_state()

    result = explain_return.generate_dual_outputs(state)

    # Graceful degrade: fallback text + xml produced, never raises.
    assert result.draft_summary_text is not None
    assert "Draft Canadian Tax Summary" in result.draft_summary_text
    assert result.draft_pseudo_xml is not None

    errors = _error_records(caplog)
    assert errors, "expected a loud ERROR-level log for the programming error"
    record = errors[0]
    assert record.exc_info is not None
    assert record.exc_info[0] is KeyError
    assert "KeyError" in (caplog.text or "")


def test_generate_dual_outputs_quiet_on_real_llm_failure(monkeypatch, capture_explain_logs):
    caplog = capture_explain_logs
    monkeypatch.setattr(
        explain_return,
        "client",
        _RaisingClient(ConnectionError("connection reset by peer")),
    )
    state = _draft_state()

    result = explain_return.generate_dual_outputs(state)

    # Graceful degrade with the canned fallback.
    assert result.draft_summary_text is not None
    assert result.draft_pseudo_xml is not None

    # Quiet: no ERROR-level loud log for an expected transport failure.
    assert not _error_records(caplog), "expected no ERROR log for an expected LLM failure"
    assert any("Output formatting fallback used:" in w for w in result.warnings)
