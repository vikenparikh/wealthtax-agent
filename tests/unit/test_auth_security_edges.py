"""Security-relevant edge branches of auth.py.

test_auth.py covers the signup/login/logout happy paths + short-password and
expired-session. These pin: verify_password never raising on a malformed hash,
the bcrypt 72-byte truncation behaviour, the null-session guard, and the
login failure paths (wrong password / unknown email).
"""

import os

import pytest

from wealthtax_agent.auth import (
    _BCRYPT_MAX,
    _bcrypt_input,
    current_user_from_session,
    hash_password,
    login,
    signup,
    verify_password,
)
from wealthtax_agent.config import reset_settings_cache
from wealthtax_agent.db import create_all_for_tests, reset_engine_cache


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


def test_verify_password_returns_false_on_malformed_hash():
    # checkpw raises on a non-bcrypt hash; verify_password must swallow -> False.
    assert verify_password("whatever", "not-a-bcrypt-hash") is False
    assert verify_password("whatever", "") is False


def test_bcrypt_input_truncates_at_72_bytes():
    assert len(_bcrypt_input("a" * 200)) == _BCRYPT_MAX == 72


def test_passwords_sharing_72_byte_prefix_verify_interchangeably():
    # Documents bcrypt's 72-byte truncation: anything past byte 72 is ignored.
    base = "a" * 72
    longer = base + "EXTRA-IGNORED"
    assert verify_password(longer, hash_password(base)) is True
    assert verify_password(base, hash_password(longer)) is True


def test_hashes_are_salted_but_both_verify():
    h1, h2 = hash_password("correct horse"), hash_password("correct horse")
    assert h1 != h2  # random per-call salt
    assert verify_password("correct horse", h1) and verify_password("correct horse", h2)


def test_current_user_from_none_or_empty_session_is_none():
    assert current_user_from_session(None) is None
    assert current_user_from_session("") is None


def test_login_wrong_password_fails_cleanly():
    signup("user@example.com", "rightpassword")
    res = login("user@example.com", "wrongpassword")
    assert res.success is False
    assert res.error == "Invalid email or password."
    assert res.session_id is None


def test_login_unknown_email_fails_cleanly():
    res = login("nobody@example.com", "whatever123")
    assert res.success is False
    assert res.error == "Invalid email or password."
