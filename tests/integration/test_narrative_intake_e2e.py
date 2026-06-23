"""End-to-end coverage of the plain-English narrative intake journey.

This exercises the *deployed* path that `main.py` runs when a user types their
year in plain English: ``parse_intake_narrative()`` produces an ``IntakeResult``
whose ``extracts`` / ``user_answers`` / ``residency_days`` are wired into a
``GraphState`` exactly the way ``_render_*`` + ``_run_wizard_generation`` do, then
the *full* compiled ``build_graph()`` pipeline runs to draft returns + filing
artifacts. The journey is otherwise only unit-tested at the parser boundary.

The LLM is stubbed at two seams so the run stays offline-deterministic:
  * ``intake.call_with_retry`` — forces the LLM happy-path of
    ``parse_intake_narrative`` (avoids the regex ``_local_fallback``, which
    mis-parses "Form 16" into phantom wages).
  * ``explain_return.client`` — mirrors ``test_pipeline_end_to_end`` so the
    explain node uses a deterministic stub instead of a real network call.

Zero source changes: this asserts only on shapes verified in the real models
(``DraftReturn.line_items`` / ``DraftReturn.estimated_tax`` /
``FilingArtifact.transmissible``) and real artifact keys
(``us_1040_pdf`` / ``in_itr_json``).
"""

from __future__ import annotations

import json

import wealthtax_agent.corrections.intake as intake
import wealthtax_agent.explain_return as explain_return
import wealthtax_agent.graph as graph
from wealthtax_agent.corrections.intake import parse_intake_narrative
from wealthtax_agent.state import GraphState


# ---- Stubbed values that must survive narrative -> graph -> engines ----

_US_WAGES = 120000.0
_US_WITHHELD = 18000.0
_IN_GROSS_SALARY = 1500000.0
_IN_TDS = 150000.0

# JSON envelope matching ``_INTAKE_SYSTEM_PROMPT``: a US W-2 + IN Form-16 year,
# single filer, India new regime, split residency.
_INTAKE_ENVELOPE = {
    "extracts": [
        {
            "form_code": "W-2",
            "jurisdiction": "US",
            "fields": {"wages": _US_WAGES, "federal_income_tax_withheld": _US_WITHHELD},
            "source_filename": "intake-narrative",
        },
        {
            "form_code": "FORM-16",
            "jurisdiction": "IN",
            "fields": {"gross_salary": _IN_GROSS_SALARY, "tds_deducted": _IN_TDS},
            "source_filename": "intake-narrative",
        },
    ],
    "user_answers": {
        "filing_status": "single",
        "state_of_residence": "CA",
        "is_indian_citizen": "yes",
        "in_regime": "new",
        "age": "32",
    },
    "residency_days": {"US": 180, "IN": 185},
    "jurisdictions": ["US", "IN"],
    "notes": ["US W-2 wages; Indian Form-16 salary."],
}


# ---- Minimal LLM-response stub (mirrors test_pipeline_end_to_end) ----


class _Msg:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Msg(content)


class _Resp:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _Completions:
    def __init__(self, content):
        self.content = content

    def create(self, **kwargs):
        return _Resp(self.content)


class _Chat:
    def __init__(self, content):
        self.completions = _Completions(content)


class _Client:
    def __init__(self, content):
        self.chat = _Chat(content)


def _stub_llm(monkeypatch):
    """Force both the intake LLM happy-path and a deterministic explain node."""
    # parse_intake_narrative: call_with_retry(_call) -> response.choices[0].message.content
    monkeypatch.setattr(
        intake,
        "call_with_retry",
        lambda _call, **_kw: _Resp(json.dumps(_INTAKE_ENVELOPE)),
    )
    # explain_return_node uses module-level client; give it a deterministic stub.
    monkeypatch.setattr(
        explain_return,
        "client",
        _Client('{"lines": {"summary": "deterministic narrative-intake explanation"}}'),
    )


def _wire_state_like_main(intake_result) -> GraphState:
    """Mirror main.py's narrative -> GraphState wiring.

    In ``main.py`` the narrative's ``IntakeResult`` flows into the wizard as:
      * ``intake.extracts``        -> ``manual_extracts`` -> ``base.extracts``
      * ``intake.user_answers``    -> ``answers``         -> ``base.user_answers``
      * ``intake.residency_days``  -> ``days_<country>``  -> ``base.residency_days``
    ``filing_year`` and ``jurisdictions`` come from the wizard selection; we take
    jurisdictions from the parsed narrative (which is what the user would pick).
    """
    base = GraphState()
    base.filing_year = 2024
    base.jurisdictions = list(intake_result.jurisdictions)
    base.user_answers.update(intake_result.user_answers)
    if intake_result.residency_days:
        base.residency_days = dict(intake_result.residency_days)
    base.extracts = list(base.extracts) + list(intake_result.extracts)
    return base


def test_narrative_intake_runs_full_graph_to_artifacts(monkeypatch):
    _stub_llm(monkeypatch)

    narrative = (
        "I'm an Indian citizen who worked in the US on a W-2 earning $120,000 "
        "(with $18,000 federal tax withheld), spent 180 days in the US then "
        "moved home and had Form 16 salary in India of Rs 15,00,000. "
        "Single filer, new India regime."
    )
    intake_result = parse_intake_narrative(narrative)

    # The parser took the stubbed LLM happy-path, not the regex fallback.
    assert intake_result.jurisdictions == ["US", "IN"]
    assert intake_result.residency_days == {"US": 180, "IN": 185}
    by_form = {e.form_code: e for e in intake_result.extracts}
    assert set(by_form) == {"W-2", "FORM-16"}
    assert by_form["W-2"].extractor == "llm"
    assert by_form["W-2"].fields["wages"] == _US_WAGES
    assert by_form["FORM-16"].fields["gross_salary"] == _IN_GROSS_SALARY

    # Wire exactly as main.py, then run the full compiled pipeline.
    base = _wire_state_like_main(intake_result)
    compiled = graph.build_graph()
    final_state = GraphState.model_validate(compiled.invoke(base))

    # Both jurisdictions produced drafts.
    assert "US" in final_state.draft_returns
    assert "IN" in final_state.draft_returns

    # Narrative's key fields survived all the way to the engines.
    assert final_state.draft_returns["US"].line_items["wages"] == _US_WAGES
    assert final_state.draft_returns["IN"].line_items["gross_salary"] == _IN_GROSS_SALARY

    # Both drafts compute positive tax.
    assert final_state.draft_returns["US"].estimated_tax > 0
    assert final_state.draft_returns["IN"].estimated_tax > 0

    # US 1040 + IN ITR artifacts exist and are non-transmissible.
    assert "us_1040_pdf" in final_state.filing_artifacts
    assert final_state.filing_artifacts["us_1040_pdf"].transmissible is False

    in_itr_keys = [k for k in final_state.filing_artifacts if k.startswith("in_itr")]
    assert in_itr_keys, "expected an in_itr* filing artifact"
    for key in in_itr_keys:
        assert final_state.filing_artifacts[key].transmissible is False


def test_narrative_intake_takes_llm_path_not_regex_fallback(monkeypatch):
    """Guard: the journey exercises the LLM envelope, so the FORM-16 extract is
    the clean Form-16 salary (extractor='llm'), not a regex-fallback artifact."""
    _stub_llm(monkeypatch)

    intake_result = parse_intake_narrative("Form 16 salary in India, US W-2 wages.")

    assert intake_result.notes == _INTAKE_ENVELOPE["notes"]
    # Every extract is tagged llm (the fallback tags them 'rule').
    assert intake_result.extracts
    assert all(e.extractor == "llm" for e in intake_result.extracts)
    # No phantom US wages from a regex mis-parse of "Form 16".
    us_extracts = [e for e in intake_result.extracts if e.jurisdiction == "US"]
    assert [e.form_code for e in us_extracts] == ["W-2"]
