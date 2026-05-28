"""Return-history Edit button pre-populates the wizard from stored fields.

The dashboard renders an Edit button per saved TaxReturn. Clicking it must
reuse the encrypted ``TaxReturn.fields`` payload to rebuild the same
``WizardState`` the user left, so a partial draft can be resumed without
re-typing.

This test asserts the contract at the data layer: ``load_wizard_draft``
returns a WizardState equal to the one ``save_wizard_draft`` persisted,
and a stranger's ``user_id`` cannot read another user's draft.
"""
from __future__ import annotations

import os

os.environ.setdefault("WEALTHTAX_MODE", "self_hosted")
os.environ.setdefault(
    "WEALTHTAX_FERNET_KEY", "8ZK4uF_jiBu3VqDOq6Mhs1aHCk7d8oxIvO34v9dW6X8="
)

import tempfile

import pytest

from wealthtax_agent.db import (
    create_all_for_tests,
    get_session,
    reset_engine_cache,
)
from wealthtax_agent.db.models import User
from wealthtax_agent.intake.wizard import (
    WizardState,
    load_wizard_draft,
    save_wizard_draft,
)


@pytest.fixture
def fresh_db(monkeypatch):
    db_path = tempfile.mktemp(suffix=".db")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    reset_engine_cache()
    create_all_for_tests()
    yield
    reset_engine_cache()
    try:
        os.unlink(db_path)
    except OSError:
        pass


def _make_user(email: str) -> str:
    with get_session() as session:
        user = User(
            email=email,
            hashed_password="$2b$12$fakehashXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
        )
        session.add(user)
        session.flush()
        return user.id


class TestEditPrefillRoundtrip:
    def test_saved_wizard_loads_back_with_same_data(self, fresh_db):
        user_id = _make_user("edit@example.com")
        wizard = WizardState(
            step=2,
            data={
                "jurisdictions": ["CA"],
                "filing_year": 2024,
                "days_ca": 365,
                "rrsp_contributions": 5000.0,
            },
        )

        with get_session() as session:
            tr = save_wizard_draft(
                session,
                user_id=user_id,
                return_id=None,
                wizard=wizard,
                filing_year=2024,
                jurisdictions=["CA"],
            )
            return_id = tr.id

        with get_session() as session:
            restored = load_wizard_draft(
                session, return_id=return_id, user_id=user_id
            )

        assert restored is not None
        assert restored == wizard, (restored, wizard)
        assert restored.data["rrsp_contributions"] == 5000.0
        assert restored.step == 2

    def test_load_rejects_other_users_returns(self, fresh_db):
        owner = _make_user("owner@example.com")
        intruder = _make_user("intruder@example.com")

        wizard = WizardState(step=1, data={"jurisdictions": ["US"]})
        with get_session() as session:
            tr = save_wizard_draft(
                session,
                user_id=owner,
                return_id=None,
                wizard=wizard,
                filing_year=2024,
                jurisdictions=["US"],
            )
            return_id = tr.id

        with get_session() as session:
            stolen = load_wizard_draft(
                session, return_id=return_id, user_id=intruder
            )

        assert stolen is None, "load_wizard_draft must reject foreign user_id"

    def test_load_returns_empty_state_when_fields_missing(self, fresh_db):
        """If the row exists but ``fields`` is empty, return a fresh WizardState."""
        user_id = _make_user("empty@example.com")
        wizard = WizardState()  # step 0, no data
        with get_session() as session:
            tr = save_wizard_draft(
                session,
                user_id=user_id,
                return_id=None,
                wizard=wizard,
                filing_year=2024,
                jurisdictions=[],
            )
            return_id = tr.id

        with get_session() as session:
            restored = load_wizard_draft(
                session, return_id=return_id, user_id=user_id
            )
        assert restored is not None
        assert restored.step == 0
