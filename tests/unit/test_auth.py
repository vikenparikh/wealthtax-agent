import os
import pytest
from datetime import datetime, timedelta

from wealthtax_agent.auth import (
    current_user_from_session,
    hash_password,
    login,
    logout,
    signup,
    verify_password,
)
from wealthtax_agent.config import reset_settings_cache
from wealthtax_agent.db import create_all_for_tests, get_session, reset_engine_cache
from wealthtax_agent.db.models import UserSession


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    if "WEALTHTAX_FERNET_KEY" not in os.environ:
        from cryptography.fernet import Fernet
        monkeypatch.setenv("WEALTHTAX_FERNET_KEY", Fernet.generate_key().decode())
    reset_settings_cache()
    reset_engine_cache()
    create_all_for_tests()
    yield


def test_hash_and_verify_password():
    hashed = hash_password("a-very-strong-password")
    assert verify_password("a-very-strong-password", hashed)
    assert not verify_password("wrong", hashed)


def test_signup_rejects_short_password():
    r = signup("x@y.com", "short", full_name="X")
    assert not r.success
    assert "8 characters" in r.error


def test_signup_rejects_invalid_email():
    r = signup("not-an-email", "longenough", full_name="X")
    assert not r.success


def test_signup_then_login_then_logout():
    r = signup("a@b.com", "longenough", full_name="A B")
    assert r.success
    bad = login("a@b.com", "wrong")
    assert not bad.success
    good = login("a@b.com", "longenough")
    assert good.success
    user = current_user_from_session(good.session_id)
    assert user is not None and user.email == "a@b.com"
    logout(good.session_id)
    assert current_user_from_session(good.session_id) is None


def test_duplicate_signup_fails():
    signup("dupe@example.com", "longenough")
    r = signup("dupe@example.com", "longenough")
    assert not r.success
    assert "already exists" in r.error


def test_expired_session_returns_no_user():
    r = signup("exp@example.com", "longenough")
    assert r.success
    with get_session() as s:
        sess = s.get(UserSession, r.session_id)
        sess.expires_at = datetime.utcnow() - timedelta(minutes=5)
    assert current_user_from_session(r.session_id) is None
