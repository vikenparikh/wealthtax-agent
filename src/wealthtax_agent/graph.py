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

from langgraph.graph import END, START, StateGraph

from wealthtax_agent.build_return import build_return_node
from wealthtax_agent.classify_forms import classify_forms_node
from wealthtax_agent.clarify import ask_clarifications_node, has_outstanding_clarifications
from wealthtax_agent.explain_return import explain_return_node, generate_dual_outputs
from wealthtax_agent.extract_forms import extract_forms_node
from wealthtax_agent.optimize import optimize_node
from wealthtax_agent.parse_docs import parse_docs_node
from wealthtax_agent.reason_tax import reason_tax_node
from wealthtax_agent.state import GraphState


def _clarification_router(state: GraphState) -> str:
    return "pause" if has_outstanding_clarifications(state) else "continue"


def build_legacy_graph():
    workflow = StateGraph(GraphState)
    workflow.add_node("parse_docs", parse_docs_node)
    workflow.add_node("reason_tax", reason_tax_node)
    workflow.add_node("build_return", build_return_node)
    workflow.add_node("explain_return", explain_return_node)
    workflow.add_node("format_outputs", generate_dual_outputs)

    workflow.add_edge(START, "parse_docs")
    workflow.add_edge("parse_docs", "reason_tax")
    workflow.add_edge("reason_tax", "build_return")
    workflow.add_edge("build_return", "explain_return")
    workflow.add_edge("explain_return", "format_outputs")
    workflow.add_edge("format_outputs", END)

    return workflow.compile()


def build_graph():
    workflow = StateGraph(GraphState)

    workflow.add_node("classify_forms", classify_forms_node)
    workflow.add_node("extract_forms", extract_forms_node)
    workflow.add_node("ask_clarifications", ask_clarifications_node)
    workflow.add_node("reason_tax", reason_tax_node)
    workflow.add_node("optimize", optimize_node)
    workflow.add_node("explain_return", explain_return_node)
    workflow.add_node("build_return", build_return_node)
    workflow.add_node("format_outputs", generate_dual_outputs)

    workflow.add_edge(START, "classify_forms")
    workflow.add_edge("classify_forms", "extract_forms")
    workflow.add_edge("extract_forms", "ask_clarifications")
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
