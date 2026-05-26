"""AC6 — Intake wizard draft survives DB session restart.

Simulates a user filling out part of the 5-step wizard, closing the browser
(new DB session), then re-opening the same return to continue from where they
left off.
"""
from __future__ import annotations

import os

import pytest

from wealthtax_agent.config import reset_settings_cache
from wealthtax_agent.db import create_all_for_tests, get_session, reset_engine_cache
from wealthtax_agent.db.models import User
from wealthtax_agent.intake.wizard import (
    WizardState,
    WIZARD_STEP_COUNT,
    WIZARD_STEPS,
    load_wizard_draft,
    save_wizard_draft,
)


_FERNET_KEY = "8ZK4uF_jiBu3VqDOq6Mhs1aHCk7d8oxIvO34v9dW6X8="


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch, tmp_path):
    db_file = tmp_path / "test_wizard.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("WEALTHTAX_FERNET_KEY", _FERNET_KEY)
    reset_settings_cache()
    reset_engine_cache()
    create_all_for_tests()
    yield
    reset_engine_cache()
    reset_settings_cache()


def _make_user(session) -> User:
    u = User(
        email="wizard-test@example.com",
        hashed_password="$2b$12$fakehashXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
    )
    session.add(u)
    session.flush()
    return u


# ---- WizardState unit tests ----

def test_wizard_initial_state():
    w = WizardState()
    assert w.step == 0
    assert w.current_step_name == WIZARD_STEPS[0]
    assert w.progress_label == "1/5"
    assert w.can_go_back() is False
    assert w.can_advance() is True


def test_wizard_advance_through_all_steps():
    w = WizardState()
    w = w.advance({"jurisdictions": ["CA"], "filing_year": 2024})
    assert w.step == 1
    w = w.advance({"residency_days": {"CA": 365}})
    assert w.step == 2
    w = w.advance({"income_sources": {"CA": {"employment_income": 80000}}})
    assert w.step == 3
    w = w.advance({"deductions": {"rrsp_contributions": 5000}})
    assert w.step == 4
    assert w.can_advance() is False


def test_wizard_go_back():
    w = WizardState(step=2, data={"a": 1})
    w2 = w.go_back()
    assert w2.step == 1
    assert w2.data == {"a": 1}


def test_wizard_advance_preserves_earlier_data():
    w = WizardState()
    w = w.advance({"jurisdictions": ["CA", "US"]})
    w = w.advance({"residency_days": {"CA": 200, "US": 165}})
    assert w.data["jurisdictions"] == ["CA", "US"]
    assert w.data["residency_days"]["CA"] == 200


def test_wizard_cannot_advance_past_last_step():
    w = WizardState(step=WIZARD_STEP_COUNT - 1)
    with pytest.raises(ValueError, match="last step"):
        w.advance({})


def test_wizard_cannot_go_back_past_first_step():
    w = WizardState(step=0)
    with pytest.raises(ValueError, match="first step"):
        w.go_back()


def test_wizard_serialisation_round_trip():
    w = WizardState(step=2, data={"jurisdictions": ["IN"], "filing_year": 2023})
    d = w.to_dict()
    w2 = WizardState.from_dict(d)
    assert w2 == w


def test_wizard_update_data_same_step():
    w = WizardState(step=1, data={"a": 1})
    w2 = w.update_data({"b": 2})
    assert w2.step == 1
    assert w2.data == {"a": 1, "b": 2}


# ---- DB persistence tests ----

def test_draft_saved_and_loaded_from_new_session():
    """Simulate save → process restart → load in a new session."""
    wizard_at_step_2 = WizardState(
        step=2,
        data={
            "jurisdictions": ["CA"],
            "filing_year": 2024,
            "residency_days": {"CA": 365},
        },
    )

    # Save in session 1
    with get_session() as s1:
        user = _make_user(s1)
        user_id = user.id
        tr = save_wizard_draft(
            s1,
            user_id=user_id,
            return_id=None,
            wizard=wizard_at_step_2,
            filing_year=2024,
            jurisdictions=["CA"],
        )
        return_id = tr.id

    # Load in a completely new session (simulates restart)
    with get_session() as s2:
        loaded = load_wizard_draft(s2, return_id=return_id, user_id=user_id)

    assert loaded is not None, "draft should survive session close"
    assert loaded.step == 2
    assert loaded.data["residency_days"]["CA"] == 365


def test_draft_update_persisted():
    """Updating a draft (Next click on step 3) persists the new step."""
    with get_session() as s:
        user = _make_user(s)
        user_id = user.id
        tr = save_wizard_draft(
            s,
            user_id=user_id,
            return_id=None,
            wizard=WizardState(step=2, data={"filing_year": 2024}),
            filing_year=2024,
            jurisdictions=["US"],
        )
        return_id = tr.id

    # Load, advance, save
    with get_session() as s:
        wiz = load_wizard_draft(s, return_id=return_id, user_id=user_id)
        wiz_next = wiz.advance({"income_sources": {"US": {"wages": 120000}}})
        save_wizard_draft(
            s,
            user_id=user_id,
            return_id=return_id,
            wizard=wiz_next,
            filing_year=2024,
            jurisdictions=["US"],
        )

    with get_session() as s:
        reloaded = load_wizard_draft(s, return_id=return_id, user_id=user_id)
    assert reloaded.step == 3
    assert reloaded.data["income_sources"]["US"]["wages"] == 120000


def test_load_draft_wrong_user_returns_none():
    """User B must not be able to read User A's draft."""
    with get_session() as s:
        user_a = _make_user(s)
        user_b = User(email="b@example.com", hashed_password="x")
        s.add(user_b)
        s.flush()
        tr = save_wizard_draft(
            s,
            user_id=user_a.id,
            return_id=None,
            wizard=WizardState(step=1, data={}),
            filing_year=2024,
            jurisdictions=["CA"],
        )
        return_id = tr.id
        user_b_id = user_b.id

    with get_session() as s:
        result = load_wizard_draft(s, return_id=return_id, user_id=user_b_id)
    assert result is None


def test_draft_status_is_draft():
    """Wizard-saved returns must have status='draft'."""
    with get_session() as s:
        user = _make_user(s)
        tr = save_wizard_draft(
            s,
            user_id=user.id,
            return_id=None,
            wizard=WizardState(step=0, data={}),
            filing_year=2024,
            jurisdictions=["CA"],
        )
        assert tr.status == "draft"


def test_wizard_fields_encrypted_in_db():
    """Fields written by wizard must be encrypted (not plaintext) in SQLite."""
    import json
    import sqlalchemy as sa

    from wealthtax_agent.db import get_engine

    secret_data = {"filing_year": 2024, "income_sources": {"CA": {"employment_income": 99999}}}
    with get_session() as s:
        user = _make_user(s)
        tr = save_wizard_draft(
            s,
            user_id=user.id,
            return_id=None,
            wizard=WizardState(step=3, data=secret_data),
            filing_year=2024,
            jurisdictions=["CA"],
        )
        return_id = tr.id

    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT fields FROM tax_returns WHERE id = :id"),
            {"id": return_id},
        ).fetchone()

    raw = row[0]
    if isinstance(raw, str):
        raw = raw.encode("utf-8")

    plain = json.dumps(secret_data, default=str).encode("utf-8")
    assert raw != plain, "wizard fields must not be stored as plaintext"
