"""Pipeline node timing instrumentation (graph._timed).

Every pipeline node is registered through ``_add`` -> ``_timed``, which emits a
structured ``node_complete`` (or ``node_failed``) record carrying the node name
and ``duration_ms``. This gives production per-node timing without a profiler.
These tests pin the wrapper's contract:

* behaviour-preserving — returns the wrapped fn's result unchanged;
* emits ``node_complete`` with the node name + a numeric ``duration_ms``;
* on error, emits ``node_failed`` (with duration) and re-raises;
* the record carries only name + timing — no GraphState / PII.

Capture mirrors ``test_structured_logging`` (the module logger has
``propagate=False``, so we attach a StringIO handler to it directly).
"""

from __future__ import annotations

import io
import json

import pytest

import wealthtax_agent.graph as graph
from wealthtax_agent.logging_utils import get_logger, reset_loggers
from wealthtax_agent.state import GraphState


def _capture() -> io.StringIO:
    """Attach a StringIO handler to the graph module logger and return it."""
    reset_loggers(["wealthtax_agent.graph"])
    buf = io.StringIO()
    get_logger("wealthtax_agent.graph", stream=buf)
    return buf


def _records(buf: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in buf.getvalue().splitlines() if line.strip()]


def test_timed_passes_result_through_and_logs_node_complete():
    buf = _capture()
    sentinel = GraphState()

    def node(_state):
        return sentinel

    result = graph._timed("my_node", node)(GraphState())

    assert result is sentinel  # behaviour-preserving
    recs = [r for r in _records(buf) if r["msg"] == "node_complete"]
    assert len(recs) == 1
    rec = recs[0]
    assert rec["node"] == "my_node"
    assert rec["level"] == "INFO"
    assert isinstance(rec["duration_ms"], (int, float))
    assert rec["duration_ms"] >= 0.0


def test_timed_logs_node_failed_and_reraises():
    buf = _capture()

    class Boom(RuntimeError):
        pass

    def node(_state):
        raise Boom("kaboom")

    with pytest.raises(Boom):
        graph._timed("bad_node", node)(GraphState())

    recs = [r for r in _records(buf) if r["msg"] == "node_failed"]
    assert len(recs) == 1
    rec = recs[0]
    assert rec["node"] == "bad_node"
    assert rec["level"] == "WARNING"
    assert isinstance(rec["duration_ms"], (int, float))
    # No node_complete emitted on the failure path.
    assert not [r for r in _records(buf) if r["msg"] == "node_complete"]


def test_timed_preserves_wrapped_name():
    def node(_state):
        return _state

    assert graph._timed("residency_test", node).__name__ == "timed_residency_test"


def test_add_registers_a_timed_node_and_graph_still_compiles():
    # The wrapper must not break graph assembly: both graphs still compile.
    assert graph.build_graph() is not None
    assert graph.build_legacy_graph() is not None
