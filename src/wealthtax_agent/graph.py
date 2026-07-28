"""LangGraph pipeline.

Two compiled graphs are exposed:

- ``build_legacy_graph()`` keeps the original 5-node pipeline so existing
  tests / scripts that relied on direct ``parse_docs`` behavior still work.
- ``build_graph()`` is the new multi-country, multi-form pipeline:

      classify_forms
        -> extract_forms
        -> ask_clarifications
            -> (pause when high-priority answers are missing)
        -> reason_tax
        -> optimize
        -> explain_return
        -> build_return (filing artifacts)
        -> format_outputs
"""

import time

from langgraph.graph import END, START, StateGraph

from wealthtax_agent.build_return import build_return_node
from wealthtax_agent.logging_utils import get_logger

_log = get_logger("wealthtax_agent.graph")
from wealthtax_agent.classify_forms import classify_forms_node
from wealthtax_agent.clarify import ask_clarifications_node, has_outstanding_clarifications
from wealthtax_agent.corrections import apply_corrections
from wealthtax_agent.engines.residency import residency_test_node
from wealthtax_agent.explain_return import explain_return_node, generate_dual_outputs
from wealthtax_agent.extract_forms import extract_forms_node
from wealthtax_agent.ingest.dedupe import dedupe_extracts_node
from wealthtax_agent.optimize import optimize_node
from wealthtax_agent.parse_docs import parse_docs_node
from wealthtax_agent.reason_tax import reason_tax_node
from wealthtax_agent.state import GraphState


def apply_corrections_node(state: GraphState) -> GraphState:
    """Apply any staged user corrections before reasoning.

    No-op when ``state.corrections`` is empty. When corrections are present,
    they mutate ``state.extracts`` / ``state.user_answers``, increment
    ``revision_number``, and move themselves into ``applied_corrections``.
    """
    return apply_corrections(state)


def _clarification_router(state: GraphState) -> str:
    return "pause" if has_outstanding_clarifications(state) else "continue"


def _timed(name: str, fn):
    """Wrap a pipeline node so each run emits a structured timing log.

    Behaviour-preserving: returns ``fn``'s result unchanged and re-raises on
    error. Emits ``node_complete`` (info) with ``duration_ms`` on success, and
    ``node_failed`` (warning) with ``duration_ms`` before propagating an
    exception — so production can see where the pipeline spends time and which
    node failed without attaching a profiler. The record carries only the node
    name and elapsed time; no GraphState / PII is logged.
    """

    def _wrapped(state: GraphState) -> GraphState:
        start = time.perf_counter()
        try:
            result = fn(state)
        except Exception:
            elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
            _log.warning("node_failed", extra={"node": name, "duration_ms": elapsed_ms})
            raise
        elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
        _log.info("node_complete", extra={"node": name, "duration_ms": elapsed_ms})
        return result

    _wrapped.__name__ = f"timed_{name}"
    return _wrapped


def _add(workflow, name: str, fn) -> None:
    """Register ``fn`` as node ``name`` wrapped with timing instrumentation."""
    workflow.add_node(name, _timed(name, fn))


def build_legacy_graph():
    _log.info("graph_build_start", extra={"variant": "legacy"})
    workflow = StateGraph(GraphState)
    _add(workflow, "parse_docs", parse_docs_node)
    _add(workflow, "reason_tax", reason_tax_node)
    _add(workflow, "build_return", build_return_node)
    _add(workflow, "explain_return", explain_return_node)
    _add(workflow, "format_outputs", generate_dual_outputs)

    workflow.add_edge(START, "parse_docs")
    workflow.add_edge("parse_docs", "reason_tax")
    workflow.add_edge("reason_tax", "build_return")
    workflow.add_edge("build_return", "explain_return")
    workflow.add_edge("explain_return", "format_outputs")
    workflow.add_edge("format_outputs", END)

    return workflow.compile()


def build_graph():
    _log.info("graph_build_start", extra={"variant": "full"})
    workflow = StateGraph(GraphState)

    _add(workflow, "classify_forms", classify_forms_node)
    _add(workflow, "extract_forms", extract_forms_node)
    _add(workflow, "dedupe_extracts", dedupe_extracts_node)
    _add(workflow, "residency_test", residency_test_node)
    _add(workflow, "apply_corrections", apply_corrections_node)
    _add(workflow, "ask_clarifications", ask_clarifications_node)
    _add(workflow, "reason_tax", reason_tax_node)
    _add(workflow, "optimize", optimize_node)
    _add(workflow, "explain_return", explain_return_node)
    _add(workflow, "build_return", build_return_node)
    _add(workflow, "format_outputs", generate_dual_outputs)

    workflow.add_edge(START, "classify_forms")
    workflow.add_edge("classify_forms", "extract_forms")
    workflow.add_edge("extract_forms", "dedupe_extracts")
    workflow.add_edge("dedupe_extracts", "residency_test")
    workflow.add_edge("residency_test", "apply_corrections")
    workflow.add_edge("apply_corrections", "ask_clarifications")
    workflow.add_conditional_edges(
        "ask_clarifications",
        _clarification_router,
        {"pause": END, "continue": "reason_tax"},
    )
    workflow.add_edge("reason_tax", "optimize")
    workflow.add_edge("optimize", "explain_return")
    workflow.add_edge("explain_return", "build_return")
    workflow.add_edge("build_return", "format_outputs")
    workflow.add_edge("format_outputs", END)

    return workflow.compile()
