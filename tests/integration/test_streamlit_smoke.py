"""Live Streamlit smoke test — boots `main.py` via AppTest under both deployment
modes and asserts the initial render succeeds. Catches widget-binding regressions
that pytest unit tests can miss, since unit tests never instantiate Streamlit
widgets.
"""
from __future__ import annotations

import os
import tempfile

import pytest
from streamlit.testing.v1 import AppTest

from wealthtax_agent.db import create_all_for_tests, reset_engine_cache
from wealthtax_agent.config import reset_settings_cache


APP_FILE = "src/wealthtax_agent/main.py"
FERNET_KEY = "8ZK4uF_jiBu3VqDOq6Mhs1aHCk7d8oxIvO34v9dW6X8="

# The "generate" button synchronously runs the entire LangGraph pipeline
# (parse → classify → extract → residency → reason → optimize → explain → build →
# format) inside the AppTest script thread. On a loaded CI/fleet box that work
# can exceed AppTest's 30s default and raise a spurious "script run timed out"
# even though the pipeline is still progressing (not hung). The light widget
# interactions keep the fast 30s default so genuine hangs still fail quickly;
# only this known-heavy step gets a wider budget. Observed: a real red under
# parallel CPU contention that passed cleanly on a quiet re-run.
_GENERATE_TIMEOUT = 90


@pytest.fixture(autouse=True)
def _fresh_db_per_test(monkeypatch):
    db_path = tempfile.mktemp(suffix=".db")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("WEALTHTAX_FERNET_KEY", FERNET_KEY)
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test-key")
    reset_settings_cache()
    reset_engine_cache()
    create_all_for_tests()
    yield
    reset_engine_cache()
    reset_settings_cache()
    try:
        os.unlink(db_path)
    except OSError:
        pass


def _render(mode: str) -> AppTest:
    os.environ["WEALTHTAX_MODE"] = mode
    reset_settings_cache()
    at = AppTest.from_file(APP_FILE, default_timeout=30)
    at.run()
    return at


def test_self_hosted_mode_renders_main_app_without_exception():
    at = _render("self_hosted")
    assert not list(at.exception), [e.value for e in at.exception]
    titles = [t.value for t in at.title]
    assert titles, "expected at least one st.title call"
    assert any("WealthTax Agent" in t for t in titles), titles


def test_saas_mode_renders_auth_or_app_without_exception():
    at = _render("saas")
    assert not list(at.exception), [e.value for e in at.exception]
    titles = [t.value for t in at.title]
    assert titles, "expected at least one st.title call"
    assert any("WealthTax Agent" in t for t in titles), titles


def test_jurisdiction_picker_offers_all_three_countries():
    at = _render("self_hosted")
    assert not list(at.exception), [e.value for e in at.exception]
    multiselects = list(at.multiselect)
    assert multiselects, "expected the jurisdiction multiselect to be rendered"
    options = multiselects[0].options
    assert set(options) >= {"CA", "US", "IN"}, options


def test_year_picker_includes_supported_years():
    at = _render("self_hosted")
    assert not list(at.exception), [e.value for e in at.exception]
    selectboxes = list(at.selectbox)
    assert selectboxes, "expected at least the Tax-year selectbox"
    year_options = selectboxes[0].options
    assert any(int(y) >= 2024 for y in year_options), year_options


def test_manual_intake_through_wizard_captures_extract():
    """E2E: drive the manual-intake journey to Step 3 and add a 1098-E by hand.

    Seeds past the Step-2 column-nested residency widgets (advancing the wizard
    normally trips an AppTest widget-registration KeyError on the column-nested
    number_inputs), then exercises the manual-intake form end-to-end and asserts
    only the structural / rendered surface — never a computed tax figure. The
    manual path does NOT invoke the LLM or the graph (generation is Step 5).
    """
    from wealthtax_agent.intake.wizard import WizardState

    at = _render("self_hosted")
    assert not list(at.exception), [e.value for e in at.exception]

    # Land directly on Step 3 (income sources / manual intake). step=2 is the
    # zero-based index of WIZARD_STEPS[2] == "income_sources".
    at.session_state["wizard"] = WizardState(
        step=2,
        data={
            "filing_year": 2024,
            "jurisdictions": ["CA"],
            "days_ca": 300,
            "days_us": 0,
            "days_in": 0,
        },
    )
    at.run()
    assert not list(at.exception), [e.value for e in at.exception]

    # The "Which form?" selectbox is rendered and defaults to the
    # alphabetically-first SUPPORTED_INTAKE_FORMS entry (1098-E).
    form_picker = [s for s in at.selectbox if s.label == "Which form?"]
    assert form_picker, "expected the manual-intake 'Which form?' selectbox"
    assert form_picker[0].value == "1098-E", form_picker[0].value

    # Fill the student-loan-interest field and submit.
    field = at.text_input(key="mi_1098-E_student_loan_interest")
    field.set_value("2400").run()

    add_buttons = [b for b in at.button if (b.label or "").startswith("Add this")]
    assert add_buttons, "expected an 'Add this ...' form-submit button"
    add_buttons[0].click().run()

    # --- Structural / non-money assertions only ---
    assert not list(at.exception), [e.value for e in at.exception]

    extracts = at.session_state["manual_extracts"]
    assert len(extracts) == 1, extracts
    captured = extracts[0]
    assert captured.form_code == "1098-E"
    assert captured.jurisdiction == "US"
    assert "student_loan_interest" in captured.fields

    assert any("Added 1098-E" in s.value for s in at.success), [
        s.value for s in at.success
    ]
    assert any(
        "Pending manual entries" in (c.value or "") for c in at.caption
    ), [c.value for c in at.caption]


def test_manual_intake_error_is_pii_scrubbed_in_ui(monkeypatch):
    """rung-3 security: when ``manual_extract`` raises a ValueError whose message
    embeds a PII-shaped value, the UI must NOT render the raw PII via ``st.error``.

    Drives the real manual-intake form through AppTest (same Step-3 seed trick as
    ``test_manual_intake_through_wizard_captures_extract``), but monkeypatches
    ``manual_extract`` to raise a ValueError carrying an SSN-shaped string —
    standing in for any PII that could leak into that exception message. After the
    fix (``st.error(sanitize_runtime_error(str(exc)))``) the raw SSN must be
    redacted to ``[REDACTED]`` in every rendered error element.
    """
    import wealthtax_agent.intake as intake_pkg
    from wealthtax_agent.intake.wizard import WizardState

    def _raise_with_pii(*_a, **_k):
        raise ValueError("bad input near 123-45-6789 while parsing")

    # main.py does ``from wealthtax_agent.intake import manual_extract``; AppTest
    # re-executes the script under a synthetic module name, resolving that name
    # against the package ``__init__`` at run time — so patch it there.
    monkeypatch.setattr(intake_pkg, "manual_extract", _raise_with_pii)

    at = _render("self_hosted")
    assert not list(at.exception), [e.value for e in at.exception]

    at.session_state["wizard"] = WizardState(
        step=2,
        data={
            "filing_year": 2024,
            "jurisdictions": ["CA"],
            "days_ca": 300,
            "days_us": 0,
            "days_in": 0,
        },
    )
    at.run()
    assert not list(at.exception), [e.value for e in at.exception]

    # Fill a field and submit so the (patched) manual_extract is invoked.
    field = at.text_input(key="mi_1098-E_student_loan_interest")
    field.set_value("2400").run()
    add_buttons = [b for b in at.button if (b.label or "").startswith("Add this")]
    assert add_buttons, "expected an 'Add this ...' form-submit button"
    add_buttons[0].click().run()

    assert not list(at.exception), [e.value for e in at.exception]

    error_values = [e.value for e in at.error]
    assert error_values, "expected an st.error element from the failing manual_extract"
    for val in error_values:
        assert "123-45-6789" not in val, f"raw SSN leaked into UI error: {val!r}"
    # The friendly error text otherwise survives (redaction is surgical).
    assert any("[REDACTED]" in val for val in error_values), error_values


# ---------------------------------------------------------------------------
# P2-AC10 — review-report rendering must be cached by DraftReturn fingerprint.
# Reviewer UI can re-render the report many times per Streamlit rerun; the
# underlying compute step must run exactly once per distinct DraftReturn.
# ---------------------------------------------------------------------------


def test_consent_checkbox_does_not_crash():
    """Checking the Groq consent box on Step 5 must not raise StreamlitAPIException.

    The consent checkbox is bound to ``key="llm_consent_given"``; the prior code
    re-assigned that same widget-bound session_state key after the widget was
    instantiated, which Streamlit forbids. After the fix, checking consent must
    (a) not raise, and (b) still persist — enabling the "Generate draft return"
    button.
    """
    from wealthtax_agent.intake.wizard import WizardState

    at = _render("self_hosted")
    assert not list(at.exception), [e.value for e in at.exception]

    # Seed the wizard directly to the consent/review step (step index 4).
    # Advancing through earlier steps trips AppTest widget-registration errors,
    # so we jump straight to the consent screen with the minimal data it reads.
    at.session_state["wizard"] = WizardState(
        step=4,
        data={
            "filing_year": 2024,
            "jurisdictions": ["CA"],
            "days_ca": 365,
        },
    )
    at.run()
    assert not list(at.exception), [e.value for e in at.exception]

    # Now check the consent box — this is the action that crashed before the fix.
    at.checkbox(key="llm_consent_given").set_value(True).run()
    assert not list(at.exception), [e.value for e in at.exception]

    # Consent must persist → the "Generate draft return" button is enabled.
    gen = at.button(key="wiz_generate")
    assert gen.disabled is False, "Generate button should be enabled once consent is given"


def test_generate_draft_return_journey_renders_draft_and_transmissible_stamp(monkeypatch):
    """E2E: drive the full GENERATE → DRAFT-RENDERS journey via AppTest.

    Seeds straight to the consent/review step (step index 4, same trick as the
    other wizard tests to dodge the Step-2 column-nested widget KeyError), gives
    consent, clicks "Generate draft return", and asserts only the *structural*
    rendered surface — the draft expander, the transmissible stamp, the revision
    success toast — plus that every emitted filing artifact is stamped
    ``transmissible is False``. No computed tax-dollar figure is pinned.

    Hermetic: both LLM call sites in explain_return (``explain_return_node`` and
    ``generate_dual_outputs``) reference ``explain_return.call_with_retry``; we
    monkeypatch that to raise, forcing each into its deterministic local-fallback
    branch so the journey runs fully offline with zero network attempted.
    """
    import wealthtax_agent.explain_return as er
    from wealthtax_agent.intake.wizard import WizardState
    from wealthtax_agent.state import FormExtract

    def _offline_stub(*_a, **_k):
        raise RuntimeError("offline-stub")

    monkeypatch.setattr(er, "call_with_retry", _offline_stub)

    at = _render("self_hosted")
    assert not list(at.exception), [e.value for e in at.exception]

    # Seed to the consent/review step with the minimal data the generate handler
    # reads. step index 4 == WIZARD_STEPS[4] (consent/review).
    at.session_state["wizard"] = WizardState(
        step=4,
        data={"filing_year": 2024, "jurisdictions": ["CA"], "days_ca": 365},
    )
    at.session_state["manual_extracts"] = [
        FormExtract(
            form_code="T4",
            jurisdiction="CA",
            fields={"employment_income": 85000.0, "income_tax_deducted": 14000.0},
        )
    ]
    # Real session_state key the generate handler reads is "answers"
    # (main.py: base.user_answers.update(st.session_state.answers or {})).
    at.session_state["answers"] = {
        "filing_status": "single",
        "province_of_residence": "ON",
        "state_of_residence": "CA",
    }
    at.run()
    assert not list(at.exception), [e.value for e in at.exception]

    # Give consent → enables the Generate button → click it.
    at.checkbox(key="llm_consent_given").set_value(True).run()
    assert not list(at.exception), [e.value for e in at.exception]
    assert at.button(key="wiz_generate").disabled is False
    at.button(key="wiz_generate").click().run(timeout=_GENERATE_TIMEOUT)

    # --- Structural / non-money assertions only ---
    assert not list(at.exception), [e.value for e in at.exception]

    state = at.session_state["last_state"]
    assert state is not None
    # The CA engine produced a draft (not awaiting_clarification).
    assert not state.awaiting_clarification, getattr(state, "warnings", None)
    assert "CA" in state.draft_returns, list(state.draft_returns.keys())

    # Every filing artifact is stamped transmissible=False.
    arts = state.filing_artifacts
    assert arts, "expected at least one filing artifact"
    assert all(a.transmissible is False for a in arts.values())

    # Rendered draft expander + transmissible stamp + revision success toast.
    assert any("CA draft return" in str(e.label) for e in at.expander), [
        str(e.label) for e in at.expander
    ]
    assert any(
        "transmissible=false" in (c.value or "") for c in at.caption
    ), [c.value for c in at.caption]
    assert any(
        "Draft saved as revision" in s.value for s in at.success
    ), [s.value for s in at.success]


def test_generate_draft_return_journey_us_renders_draft_and_transmissible_stamp(monkeypatch):
    """E2E (US): same GENERATE → DRAFT-RENDERS journey as the CA test, but for the
    US jurisdiction. Seeds a single W-2, drives consent + generate, and asserts the
    structural rendered surface plus that every filing artifact is stamped
    ``transmissible is False``. No computed tax-dollar figure is pinned.

    Hermetic: ``explain_return.call_with_retry`` is monkeypatched to raise so both
    LLM call sites fall back to their deterministic local branch (fully offline).
    """
    import wealthtax_agent.explain_return as er
    from wealthtax_agent.intake.wizard import WizardState
    from wealthtax_agent.state import FormExtract

    def _offline_stub(*_a, **_k):
        raise RuntimeError("offline-stub")

    monkeypatch.setattr(er, "call_with_retry", _offline_stub)

    at = _render("self_hosted")
    assert not list(at.exception), [e.value for e in at.exception]

    at.session_state["wizard"] = WizardState(
        step=4,
        data={"filing_year": 2024, "jurisdictions": ["US"], "days_us": 365},
    )
    at.session_state["manual_extracts"] = [
        FormExtract(
            form_code="W-2",
            jurisdiction="US",
            fields={"wages": 90000.0, "federal_income_tax_withheld": 12000.0},
        )
    ]
    at.session_state["answers"] = {
        "filing_status": "single",
        "state_of_residence": "CA",
    }
    at.run()
    assert not list(at.exception), [e.value for e in at.exception]

    at.checkbox(key="llm_consent_given").set_value(True).run()
    assert not list(at.exception), [e.value for e in at.exception]
    assert at.button(key="wiz_generate").disabled is False
    at.button(key="wiz_generate").click().run(timeout=_GENERATE_TIMEOUT)

    # --- Structural / non-money assertions only ---
    assert not list(at.exception), [e.value for e in at.exception]

    state = at.session_state["last_state"]
    assert state is not None
    assert not state.awaiting_clarification, getattr(state, "warnings", None)
    assert "US" in state.draft_returns, list(state.draft_returns.keys())

    arts = state.filing_artifacts
    assert arts, "expected at least one filing artifact"
    assert all(a.transmissible is False for a in arts.values())

    assert any("US draft return" in str(e.label) for e in at.expander), [
        str(e.label) for e in at.expander
    ]
    assert any(
        "transmissible=false" in (c.value or "") for c in at.caption
    ), [c.value for c in at.caption]
    assert any(
        "Draft saved as revision" in s.value for s in at.success
    ), [s.value for s in at.success]


def test_generate_draft_return_journey_in_renders_draft_and_transmissible_stamp(monkeypatch):
    """E2E (IN): same GENERATE → DRAFT-RENDERS journey as the CA test, but for the
    India jurisdiction (new regime). Seeds a single Form 16, drives consent +
    generate, and asserts the structural rendered surface plus that every filing
    artifact is stamped ``transmissible is False``. No computed tax-dollar figure
    is pinned.

    Hermetic: ``explain_return.call_with_retry`` is monkeypatched to raise so both
    LLM call sites fall back to their deterministic local branch (fully offline).
    """
    import wealthtax_agent.explain_return as er
    from wealthtax_agent.intake.wizard import WizardState
    from wealthtax_agent.state import FormExtract

    def _offline_stub(*_a, **_k):
        raise RuntimeError("offline-stub")

    monkeypatch.setattr(er, "call_with_retry", _offline_stub)

    at = _render("self_hosted")
    assert not list(at.exception), [e.value for e in at.exception]

    at.session_state["wizard"] = WizardState(
        step=4,
        data={
            "filing_year": 2024,
            "jurisdictions": ["IN"],
            "days_in": 300,
            "india_regime": "new",
        },
    )
    at.session_state["manual_extracts"] = [
        FormExtract(
            form_code="FORM-16",
            jurisdiction="IN",
            fields={"gross_salary": 1200000.0, "tds_deducted": 100000.0},
        )
    ]
    at.session_state["answers"] = {
        "is_indian_citizen": "yes",
        "age": "35",
    }
    at.run()
    assert not list(at.exception), [e.value for e in at.exception]

    at.checkbox(key="llm_consent_given").set_value(True).run()
    assert not list(at.exception), [e.value for e in at.exception]
    assert at.button(key="wiz_generate").disabled is False
    at.button(key="wiz_generate").click().run(timeout=_GENERATE_TIMEOUT)

    # --- Structural / non-money assertions only ---
    assert not list(at.exception), [e.value for e in at.exception]

    state = at.session_state["last_state"]
    assert state is not None
    assert not state.awaiting_clarification, getattr(state, "warnings", None)
    assert "IN" in state.draft_returns, list(state.draft_returns.keys())

    arts = state.filing_artifacts
    assert arts, "expected at least one filing artifact"
    assert all(a.transmissible is False for a in arts.values())

    assert any("IN draft return" in str(e.label) for e in at.expander), [
        str(e.label) for e in at.expander
    ]
    assert any(
        "transmissible=false" in (c.value or "") for c in at.caption
    ), [c.value for c in at.caption]
    assert any(
        "Draft saved as revision" in s.value for s in at.success
    ), [s.value for s in at.success]


class TestReviewReportCache:
    @staticmethod
    def _sample_draft():
        from wealthtax_agent.state import DraftReturn

        return DraftReturn(
            jurisdiction="CA",
            tax_year=2024,
            total_income=85_000.0,
            taxable_income=80_000.0,
            estimated_tax=14_500.0,
            estimated_refund=200.0,
            line_items={"rrsp_deduction": 5_000.0},
            totals={
                "total_income": 85_000.0,
                "taxable_income": 80_000.0,
                "total_tax": 14_500.0,
                "refund": 200.0,
                "balance_owing": 0.0,
            },
        )

    def test_render_review_report_caches_by_draft_fingerprint(self):
        """Two render calls with the same draft → one engine-compute call."""
        import unittest.mock as mock

        from wealthtax_agent import render_review_report as rrr

        rrr.clear_review_report_cache()
        draft = self._sample_draft()

        with mock.patch(
            "wealthtax_agent.render_review_report.compute_review_totals",
            wraps=rrr.compute_review_totals,
        ) as spy:
            first = rrr.render_review_report(draft, reviewer_name="Reviewer A")
            second = rrr.render_review_report(draft, reviewer_name="Reviewer A")

        assert spy.call_count == 1, (
            f"expected exactly one engine compute, got {spy.call_count}"
        )
        assert first == second
        assert "Total tax:" in first
        assert "14,500.00" in first

    def test_distinct_drafts_each_trigger_compute(self):
        """Cache must key on draft fingerprint — different draft → new compute."""
        import unittest.mock as mock

        from wealthtax_agent import render_review_report as rrr

        rrr.clear_review_report_cache()
        draft_a = self._sample_draft()
        draft_b = self._sample_draft()
        draft_b.total_income = 90_000.0
        draft_b.totals["total_income"] = 90_000.0

        with mock.patch(
            "wealthtax_agent.render_review_report.compute_review_totals",
            wraps=rrr.compute_review_totals,
        ) as spy:
            rrr.render_review_report(draft_a, reviewer_name="R")
            rrr.render_review_report(draft_b, reviewer_name="R")

        assert spy.call_count == 2

    def test_clear_cache_forces_recompute(self):
        import unittest.mock as mock

        from wealthtax_agent import render_review_report as rrr

        rrr.clear_review_report_cache()
        draft = self._sample_draft()

        with mock.patch(
            "wealthtax_agent.render_review_report.compute_review_totals",
            wraps=rrr.compute_review_totals,
        ) as spy:
            rrr.render_review_report(draft)
            rrr.clear_review_report_cache()
            rrr.render_review_report(draft)

        assert spy.call_count == 2
