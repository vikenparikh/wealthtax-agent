import wealthtax_agent.graph as graph
from wealthtax_agent.state import GraphState


def test_graph_executes_nodes_in_expected_order(monkeypatch):
    order = []

    def parse_node(state):
        order.append("parse_docs")
        return state

    def reason_node(state):
        order.append("reason_tax")
        return state

    def build_node(state):
        order.append("build_return")
        return state

    def explain_node(state):
        order.append("explain_return")
        return state

    monkeypatch.setattr(graph, "parse_docs_node", parse_node)
    monkeypatch.setattr(graph, "reason_tax_node", reason_node)
    monkeypatch.setattr(graph, "build_return_node", build_node)
    monkeypatch.setattr(graph, "explain_return_node", explain_node)

    compiled = graph.build_graph()
    compiled.invoke(GraphState())

    assert order == ["parse_docs", "reason_tax", "build_return", "explain_return"]
