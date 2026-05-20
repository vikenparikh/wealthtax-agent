"""Shared fixtures for cross-border user scenarios.

Each scenario runs the full graph end-to-end with a stubbed LLM (so the rule-
based extractors and engines do all the work). The ``scenario_state`` fixture
returns the final ``GraphState`` after the pipeline has run.
"""

from __future__ import annotations

import pytest

from wealthtax_agent.graph import build_graph
from wealthtax_agent.state import GraphState


@pytest.fixture
def build_state():
    """Factory: build a fully-resolved GraphState from a kwargs dict."""

    def _build(
        *,
        jurisdictions: list[str],
        extracts: list,
        residency_days: dict[str, int] | None = None,
        user_answers: dict[str, str] | None = None,
        filing_year: int = 2024,
    ) -> GraphState:
        return GraphState(
            jurisdictions=jurisdictions,
            extracts=extracts,
            residency_days=residency_days or {},
            user_answers=user_answers or {},
            filing_year=filing_year,
        )

    return _build


@pytest.fixture
def run_graph():
    """Compile the graph once per test and return its ``invoke`` callable."""
    graph = build_graph()

    def _run(state: GraphState) -> GraphState:
        return GraphState.model_validate(graph.invoke(state))

    return _run
