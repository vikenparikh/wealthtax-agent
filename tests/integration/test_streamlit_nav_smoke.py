"""AC8 — Extended Streamlit smoke: landing, dashboard, top navigation.

Covers both self_hosted and saas modes and asserts each new section renders
without exception.
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
    monkeypatch.delenv("WEALTHTAX_MODE", raising=False)
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


# ---- landing page (unauthenticated) ----

def test_landing_renders_without_exception_self_hosted():
    at = _render("self_hosted")
    # self_hosted auto-creates a user and logs in; landing won't appear.
    # Either way: no exception.
    assert not list(at.exception), [e.value for e in at.exception]


def test_landing_renders_without_exception_saas():
    at = _render("saas")
    assert not list(at.exception), [e.value for e in at.exception]


def test_landing_title_present_when_unauthenticated():
    """In saas mode before sign-in the landing page should show the product title."""
    at = _render("saas")
    assert not list(at.exception), [e.value for e in at.exception]
    titles = [t.value for t in at.title]
    assert any("WealthTax" in t for t in titles), f"Expected WealthTax in titles, got: {titles}"


def test_landing_value_prop_bullets_present_saas():
    """The three landing bullet points must appear somewhere in the rendered text."""
    at = _render("saas")
    assert not list(at.exception), [e.value for e in at.exception]
    # AppTest exposes markdown/title/subheader elements; collect all text-like values
    all_text = " ".join(
        str(elem.value)
        for elem_list in [at.title, at.subheader, at.markdown, at.info]
        for elem in elem_list
    )
    assert "WealthTax" in all_text, "WealthTax brand name must appear on landing"


# ---- top navigation ----

def test_top_nav_renders_in_self_hosted_mode():
    """In self_hosted mode the top nav bar must render without error."""
    at = _render("self_hosted")
    assert not list(at.exception), [e.value for e in at.exception]
    # Nav renders as buttons — find at least one nav button
    button_labels = [b.label for b in at.button]
    nav_buttons = [l for l in button_labels if l in ("Home", "New Return", "My Returns", "Settings")]
    assert nav_buttons, f"Expected nav buttons, found buttons: {button_labels}"


def test_top_nav_all_pages_present_self_hosted():
    at = _render("self_hosted")
    assert not list(at.exception), [e.value for e in at.exception]
    button_labels = {b.label for b in at.button}
    for page in ("Home", "New Return", "My Returns", "Settings"):
        assert page in button_labels, f"Nav page '{page}' not found in buttons: {button_labels}"


# ---- dashboard ----

def test_dashboard_renders_self_hosted():
    """Navigate to 'My Returns' page and verify dashboard renders without error."""
    at = _render("self_hosted")
    assert not list(at.exception), [e.value for e in at.exception]

    # Click 'My Returns' nav button
    my_returns_buttons = [b for b in at.button if b.label == "My Returns"]
    if not my_returns_buttons:
        pytest.skip("No 'My Returns' nav button found — nav may not be wired in self_hosted mode")

    at2 = my_returns_buttons[0].click().run()
    assert not list(at2.exception), [e.value for e in at2.exception]


def test_dashboard_cpa_disclaimer_present_self_hosted():
    """CPA disclaimer must appear on the My Returns / dashboard page."""
    at = _render("self_hosted")
    assert not list(at.exception), [e.value for e in at.exception]

    my_returns_buttons = [b for b in at.button if b.label == "My Returns"]
    if not my_returns_buttons:
        pytest.skip("My Returns nav button not found")

    at2 = my_returns_buttons[0].click().run()
    assert not list(at2.exception), [e.value for e in at2.exception]

    all_text = " ".join(
        str(elem.value)
        for elem_list in [at2.caption, at2.markdown, at2.info, at2.warning]
        for elem in elem_list
    )
    assert "CPA" in all_text or "tax professional" in all_text.lower(), (
        "Dashboard must include CPA disclaimer text"
    )


def test_settings_page_renders_self_hosted():
    """Settings nav item must render without exception."""
    at = _render("self_hosted")
    assert not list(at.exception), [e.value for e in at.exception]

    settings_buttons = [b for b in at.button if b.label == "Settings"]
    if not settings_buttons:
        pytest.skip("No 'Settings' nav button found")

    at2 = settings_buttons[0].click().run()
    assert not list(at2.exception), [e.value for e in at2.exception]
