"""Two users in the same DB; user A cannot read user B's data."""

import os
import pytest
from cryptography.fernet import Fernet

from wealthtax_agent.config import reset_settings_cache
from wealthtax_agent.db import create_all_for_tests, get_session, reset_engine_cache
from wealthtax_agent.db.repo import (
    create_user,
    get_return,
    list_user_returns,
    save_revision,
    start_return,
)


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    if "WEALTHTAX_FERNET_KEY" not in os.environ:
        monkeypatch.setenv("WEALTHTAX_FERNET_KEY", Fernet.generate_key().decode())
    reset_settings_cache()
    reset_engine_cache()
    create_all_for_tests()
    yield


def test_user_b_cannot_read_user_a_returns():
    with get_session() as s:
        a = create_user(s, email="a@x.com", hashed_password="ha")
        b = create_user(s, email="b@x.com", hashed_password="hb")
        ret_a = start_return(s, user_id=a.id, filing_year=2024, jurisdictions=["CA"])
        ret_b = start_return(s, user_id=b.id, filing_year=2024, jurisdictions=["US"])
        save_revision(s, user_id=a.id, return_id=ret_a.id,
                      state_json={"filing_year": 2024, "owner": "a"},
                      summary_totals_json={"CA": {"total_tax": 12000.0}},
                      form_snapshots=[])
        save_revision(s, user_id=b.id, return_id=ret_b.id,
                      state_json={"filing_year": 2024, "owner": "b"},
                      summary_totals_json={"US": {"total_tax": 9000.0}},
                      form_snapshots=[])
        a_id, b_id, ret_a_id, ret_b_id = a.id, b.id, ret_a.id, ret_b.id

    with get_session() as s:
        # B cannot fetch A's return by id
        assert get_return(s, user_id=b_id, return_id=ret_a_id) is None
        # A cannot fetch B's return by id
        assert get_return(s, user_id=a_id, return_id=ret_b_id) is None
        # Each user's list only contains their own returns
        a_returns = list_user_returns(s, a_id)
        b_returns = list_user_returns(s, b_id)
        assert {r.id for r in a_returns} == {ret_a_id}
        assert {r.id for r in b_returns} == {ret_b_id}


def test_save_revision_for_wrong_user_raises():
    with get_session() as s:
        a = create_user(s, email="a2@x.com", hashed_password="ha")
        b = create_user(s, email="b2@x.com", hashed_password="hb")
        ret_a = start_return(s, user_id=a.id, filing_year=2024, jurisdictions=["CA"])
        a_id, b_id, ret_a_id = a.id, b.id, ret_a.id

    with get_session() as s:
        with pytest.raises(ValueError):
            save_revision(s, user_id=b_id, return_id=ret_a_id,
                          state_json={}, summary_totals_json={}, form_snapshots=[])
