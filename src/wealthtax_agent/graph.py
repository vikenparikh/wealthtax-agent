from langgraph.graph import END, START, StateGraph

from wealthtax_agent.build_return import build_return_node
from wealthtax_agent.explain_return import explain_return_node, generate_dual_outputs
from wealthtax_agent.parse_docs import parse_docs_node
from wealthtax_agent.reason_tax import reason_tax_node
from wealthtax_agent.state import GraphState


def build_graph():
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
