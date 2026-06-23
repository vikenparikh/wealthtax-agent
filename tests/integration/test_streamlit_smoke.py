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


APP_FILE = "src/wealthtax_agent/main.py"
FERNET_KEY = "8ZK4uF_jiBu3VqDOq6Mhs1aHCk7d8oxIvO34v9dW6X8="


@pytest.fixture(autouse=True)
def _fresh_db_per_test(monkeypatch):
    db_path = tempfile.mktemp(suffix=".db")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("WEALTHTAX_FERNET_KEY", FERNET_KEY)
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test-key")
    reset_engine_cache()
    create_all_for_tests()
    yield
    reset_engine_cache()
    try:
        os.unlink(db_path)
    except OSError:
        pass


def _render(mode: str) -> AppTest:
    os.environ["WEALTHTAX_MODE"] = mode
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


# ---------------------------------------------------------------------------
# P2-AC10 — review-report rendering must be cached by DraftReturn fingerprint.
# Reviewer UI can re-render the report many times per Streamlit rerun; the
# underlying compute step must run exactly once per distinct DraftReturn.
# ---------------------------------------------------------------------------


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
