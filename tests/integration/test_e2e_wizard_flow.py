"""P2-AC9 — End-to-end wizard flow.

A pytest fixture walks all 5 steps of the wizard state machine
(``WizardState``), submitting valid data at each step, then feeds the
resulting wizard payload into the compiled LangGraph pipeline. The final
``GraphState`` is asserted to contain a ``draft_return`` whose
``estimated_tax`` is > 0 and at least one ``FilingArtifact`` per selected
jurisdiction.

Env contract (matches the AC):
- ``WEALTHTAX_MODE=self_hosted``
- ``GROQ_API_KEY=gsk-test-key`` (never reaches the network — LLM is mocked)
- ``WEALTHTAX_FERNET_KEY`` is a valid Fernet-shape placeholder for any
  DB code that touches encrypted columns.

The LLM client is patched at module level so no real network call is ever
issued: any call into ``wealthtax_agent.llm`` returns a static stub.
"""
from __future__ import annotations

import os

# Required env BEFORE any wealthtax_agent import so module-level config picks
# them up. Keep these synced with the AC text.
os.environ.setdefault("WEALTHTAX_MODE", "self_hosted")
os.environ.setdefault("GROQ_API_KEY", "gsk-test-key")
os.environ.setdefault(
    "WEALTHTAX_FERNET_KEY", "8ZK4uF_jiBu3VqDOq6Mhs1aHCk7d8oxIvO34v9dW6X8="
)

import pytest

from wealthtax_agent.graph import build_graph
from wealthtax_agent.intake.wizard import (
    WIZARD_STEPS,
    WIZARD_STEP_COUNT,
    WizardState,
)
from wealthtax_agent.state import FormExtract, GraphState


# ---------------------------------------------------------------------------
# Wizard-walk fixture: steps 1..5 with valid data at each step
# ---------------------------------------------------------------------------


def _walk_wizard(step_payloads: list[dict]) -> WizardState:
    """Advance a fresh WizardState through each payload in order.

    Each payload is the dict the UI would pass to ``advance()`` for that
    step. We assert the step index after every advance so a regression in
    the state machine fails loudly with the offending step name.
    """
    assert len(step_payloads) == WIZARD_STEP_COUNT - 1, (
        f"need {WIZARD_STEP_COUNT - 1} payloads (advance count), got "
        f"{len(step_payloads)}"
    )
    wiz = WizardState()
    assert wiz.step == 0, "fresh wizard must start at step 0"
    for i, payload in enumerate(step_payloads):
        wiz = wiz.advance(payload)
        assert wiz.step == i + 1, (
            f"after submitting step {WIZARD_STEPS[i]!r}, expected wizard at "
            f"step {i + 1} ({WIZARD_STEPS[i + 1]!r}), got step {wiz.step}"
        )
    return wiz


@pytest.fixture
def wizard_ca_only() -> WizardState:
    """Single-jurisdiction (CA) walk that exercises every step."""
    return _walk_wizard(
        [
            # step 1 → step 2: jurisdiction + year
            {"jurisdictions": ["CA"], "filing_year": 2024},
            # step 2 → step 3: residency days
            {"days_ca": 365, "days_us": 0, "days_in": 0},
            # step 3 → step 4: income sources (just a flag the UI sets)
            {"income_sources_confirmed": True},
            # step 4 → step 5: deductions / credits
            {"deductions_confirmed": True, "rrsp_contributions": 5000.0},
        ]
    )


@pytest.fixture
def wizard_ca_us() -> WizardState:
    """Cross-border (CA + US) walk that exercises every step."""
    return _walk_wizard(
        [
            {"jurisdictions": ["CA", "US"], "filing_year": 2024},
            {"days_ca": 200, "days_us": 165, "days_in": 0},
            {"income_sources_confirmed": True},
            {"deductions_confirmed": True},
        ]
    )


@pytest.fixture
def patch_llm(monkeypatch):
    """Patch wealthtax_agent.llm public API so no real network call is made.

    The rule-based extractors used by the scenarios path do not call the
    LLM, but ``explain_return`` and ``optimize`` can. We stub the client
    factory + the OpenAI-compatible response so any accidental call
    returns deterministic text instead of raising.
    """
    from wealthtax_agent import llm as llm_mod

    class _StubChoice:
        def __init__(self, content: str = "stub"):
            self.message = type("M", (), {"content": content})()

    class _StubResponse:
        def __init__(self, content: str = "stub"):
            self.choices = [_StubChoice(content)]

    class _StubChatCompletions:
        def create(self, **_kwargs):
            return _StubResponse()

    class _StubChat:
        completions = _StubChatCompletions()

    class _StubClient:
        chat = _StubChat()

    monkeypatch.setattr(llm_mod, "get_client", lambda *a, **kw: _StubClient())
    monkeypatch.setattr(llm_mod, "get_api_key", lambda *a, **kw: "gsk-test-key")
    yield


# ---------------------------------------------------------------------------
# 5-step state-machine contract
# ---------------------------------------------------------------------------


class TestWizardWalkContract:
    def test_walk_ca_only_reaches_review_submit(self, wizard_ca_only):
        assert wizard_ca_only.step == WIZARD_STEP_COUNT - 1
        assert wizard_ca_only.current_step_name == "review_submit"

    def test_walk_ca_us_reaches_review_submit(self, wizard_ca_us):
        assert wizard_ca_us.step == WIZARD_STEP_COUNT - 1
        assert wizard_ca_us.current_step_name == "review_submit"

    def test_walk_ca_only_carries_all_payload_keys(self, wizard_ca_only):
        d = wizard_ca_only.data
        assert d["jurisdictions"] == ["CA"]
        assert d["filing_year"] == 2024
        assert d["days_ca"] == 365
        assert d["income_sources_confirmed"] is True
        assert d["deductions_confirmed"] is True
        assert d["rrsp_contributions"] == 5000.0

    def test_walk_ca_us_carries_all_jurisdictions(self, wizard_ca_us):
        d = wizard_ca_us.data
        assert set(d["jurisdictions"]) == {"CA", "US"}
        assert d["days_us"] == 165


# ---------------------------------------------------------------------------
# Graph drives wizard data to a populated DraftReturn + filing artifacts
# ---------------------------------------------------------------------------


def _wizard_to_state(
    wiz: WizardState,
    *,
    extracts: list[FormExtract],
    user_answers: dict[str, str] | None = None,
) -> GraphState:
    """Bridge the wizard payload to a ``GraphState`` ready for the graph.

    The UI does this same translation just before calling ``build_graph()``.
    We keep it as a small helper here so the test reads like the UI flow.
    """
    return GraphState(
        jurisdictions=list(wiz.data["jurisdictions"]),
        filing_year=int(wiz.data["filing_year"]),
        residency_days={
            "CA": int(wiz.data.get("days_ca", 0)),
            "US": int(wiz.data.get("days_us", 0)),
            "IN": int(wiz.data.get("days_in", 0)),
        },
        extracts=extracts,
        user_answers=user_answers or {},
    )


class TestE2EWizardToGraph:
    def test_ca_only_flow_produces_draft_return_and_t1_artifact(
        self, wizard_ca_only, patch_llm
    ):
        extracts = [
            FormExtract(
                form_code="T4",
                jurisdiction="CA",
                fields={
                    "employment_income": 100_000.0,
                    "income_tax_deducted": 22_000.0,
                    "cpp_contributions": 3_500.0,
                    "ei_premiums": 1_000.0,
                },
            ),
        ]
        state = _wizard_to_state(
            wizard_ca_only,
            extracts=extracts,
            user_answers={
                "province_of_residence": "ON",
                "filing_status": "single",
                "age": "35",
            },
        )

        graph = build_graph()
        final = GraphState.model_validate(graph.invoke(state))

        # DraftReturn populated for CA with a positive tax estimate.
        assert "CA" in final.draft_returns, sorted(final.draft_returns)
        ca_draft = final.draft_returns["CA"]
        assert ca_draft.estimated_tax > 0, (
            f"expected CA estimated_tax > 0, got {ca_draft.estimated_tax}"
        )

        # At least one filing artifact for the selected jurisdiction (CA),
        # and every artifact must be transmissible=False (safety invariant).
        ca_artifacts = [
            a
            for a in final.filing_artifacts.values()
            if a.jurisdiction == "CA"
        ]
        assert ca_artifacts, "expected ≥1 CA filing artifact"
        assert all(a.transmissible is False for a in ca_artifacts)

    def test_ca_us_flow_produces_artifact_per_jurisdiction(
        self, wizard_ca_us, patch_llm
    ):
        extracts = [
            FormExtract(
                form_code="T4",
                jurisdiction="CA",
                fields={
                    "employment_income": 60_000.0,
                    "income_tax_deducted": 12_000.0,
                },
            ),
            FormExtract(
                form_code="W-2",
                jurisdiction="US",
                fields={
                    "wages": 50_000.0,
                    "federal_income_tax_withheld": 7_500.0,
                },
            ),
        ]
        state = _wizard_to_state(
            wizard_ca_us,
            extracts=extracts,
            user_answers={
                "province_of_residence": "ON",
                "state_of_residence": "CA",
                "filing_status": "single",
                "age": "40",
            },
        )

        graph = build_graph()
        final = GraphState.model_validate(graph.invoke(state))

        # Both jurisdictions produced a draft return.
        assert "CA" in final.draft_returns and "US" in final.draft_returns
        total_tax = sum(d.estimated_tax for d in final.draft_returns.values())
        assert total_tax > 0, f"expected combined estimated_tax > 0, got {total_tax}"

        # At least one filing artifact per selected jurisdiction (the AC).
        per_juris = {"CA": 0, "US": 0}
        for a in final.filing_artifacts.values():
            if a.jurisdiction in per_juris:
                per_juris[a.jurisdiction] += 1
        assert per_juris["CA"] >= 1, per_juris
        assert per_juris["US"] >= 1, per_juris


# ---------------------------------------------------------------------------
# AppTest smoke — confirms the wizard renders without exception in the same
# env that the wizard-walk fixture exercises. This is the "via AppTest"
# clause of the AC: the wizard UI must boot under the wired env so a future
# regression in widget binding fails this test instead of escaping to prod.
# ---------------------------------------------------------------------------


def test_wizard_app_boots_without_exception_in_self_hosted_mode(monkeypatch):
    import tempfile

    from streamlit.testing.v1 import AppTest

    from wealthtax_agent.db import create_all_for_tests, reset_engine_cache

    db_path = tempfile.mktemp(suffix=".db")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("WEALTHTAX_MODE", "self_hosted")
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test-key")
    monkeypatch.setenv(
        "WEALTHTAX_FERNET_KEY", "8ZK4uF_jiBu3VqDOq6Mhs1aHCk7d8oxIvO34v9dW6X8="
    )
    reset_engine_cache()
    create_all_for_tests()
    try:
        at = AppTest.from_file(
            "src/wealthtax_agent/main.py", default_timeout=30
        )
        at.run()
        assert not list(at.exception), [e.value for e in at.exception]
        # Wizard step labels are exposed via the WIZARD_STEPS constant; the
        # multiselect for jurisdictions belongs to the wizard's step 1.
        multiselects = list(at.multiselect)
        assert multiselects, "expected wizard step-1 multiselect to render"
        assert set(multiselects[0].options) >= {"CA", "US", "IN"}
    finally:
        reset_engine_cache()
        try:
            os.unlink(db_path)
        except OSError:
            pass
