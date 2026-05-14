import wealthtax_agent.graph as graph
from wealthtax_agent.state import GraphState


def test_graph_executes_nodes_in_expected_order(monkeypatch):
    order = []

    def make_recorder(name):
        def _node(state):
            order.append(name)
            return state
        return _node

    monkeypatch.setattr(graph, "classify_forms_node", make_recorder("classify_forms"))
    monkeypatch.setattr(graph, "extract_forms_node", make_recorder("extract_forms"))
    monkeypatch.setattr(graph, "ask_clarifications_node", make_recorder("ask_clarifications"))
    monkeypatch.setattr(graph, "reason_tax_node", make_recorder("reason_tax"))
    monkeypatch.setattr(graph, "optimize_node", make_recorder("optimize"))
    monkeypatch.setattr(graph, "explain_return_node", make_recorder("explain_return"))
    monkeypatch.setattr(graph, "build_return_node", make_recorder("build_return"))

    def passthrough_format(state):
        order.append("format_outputs")
        return state

    monkeypatch.setattr(graph, "generate_dual_outputs", passthrough_format)
    monkeypatch.setattr(graph, "has_outstanding_clarifications", lambda state: False)

    compiled = graph.build_graph()
    compiled.invoke(GraphState())

    assert order == [
        "classify_forms",
        "extract_forms",
        "ask_clarifications",
        "reason_tax",
        "optimize",
        "explain_return",
        "build_return",
        "format_outputs",
    ]


def test_legacy_graph_preserves_original_pipeline(monkeypatch):
    order = []

    def make_recorder(name):
        def _node(state):
            order.append(name)
            return state
        return _node

    monkeypatch.setattr(graph, "parse_docs_node", make_recorder("parse_docs"))
    monkeypatch.setattr(graph, "reason_tax_node", make_recorder("reason_tax"))
    monkeypatch.setattr(graph, "build_return_node", make_recorder("build_return"))
    monkeypatch.setattr(graph, "explain_return_node", make_recorder("explain_return"))
    monkeypatch.setattr(graph, "generate_dual_outputs", make_recorder("format_outputs"))

    compiled = graph.build_legacy_graph()
    compiled.invoke(GraphState())

    assert order == ["parse_docs", "reason_tax", "build_return", "explain_return", "format_outputs"]
