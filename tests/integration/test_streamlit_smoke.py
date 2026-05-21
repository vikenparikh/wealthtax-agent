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
