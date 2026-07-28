"""Brute-force backoff on login — delay-NOT-lockout (MODERATE security).

These tests pin BOTH safety properties of the email-scoped backoff added to
``auth.login``:

  1. FAIL-OPEN: a legit user with the CORRECT password ALWAYS succeeds, even
     after many prior failed attempts. This is the critical safety property —
     the backoff must never stand between a real user and their tax data.
  2. BRUTE-FORCE SLOWED: once recent failures exceed the threshold, the next
     FAILED attempt is throttled (returns a "Too many attempts" signal).
  3. SUCCESS RESETS the counter, so a single later failure is not throttled.

Fixture style mirrors test_auth.py / test_auth_security_edges.py (in-memory
SQLite via ``create_all_for_tests``).
"""

import os

import pytest

from wealthtax_agent.auth import (
    _BACKOFF_THRESHOLD,
    _backoff_seconds,
    login,
    signup,
)
from wealthtax_agent.config import reset_settings_cache
from wealthtax_agent.db import create_all_for_tests, get_session, reset_engine_cache
from wealthtax_agent.db.repo import get_user_by_email


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


_EMAIL = "backoff@example.com"
_PASSWORD = "correct-horse-battery"


def _fail_n_times(n: int) -> None:
    for _ in range(n):
        res = login(_EMAIL, "wrong-password")
        assert res.success is False


# --------------------------------------------------------------------------
# Property 1 (CRITICAL): correct password ALWAYS succeeds — never blocked.
# --------------------------------------------------------------------------

def test_correct_password_succeeds_even_after_many_failures():
    signup(_EMAIL, _PASSWORD)
    # Blow way past the throttle threshold with wrong passwords.
    _fail_n_times(_BACKOFF_THRESHOLD + 10)

    good = login(_EMAIL, _PASSWORD)
    assert good.success is True, "legit user must never be locked out by backoff"
    assert good.session_id is not None
    assert good.error is None


def test_backoff_never_hard_locks_between_throttled_failures():
    """Even while throttled, presenting the right password logs in immediately."""
    signup(_EMAIL, _PASSWORD)
    _fail_n_times(_BACKOFF_THRESHOLD + 3)

    # The next FAILED attempt is throttled...
    throttled = login(_EMAIL, "still-wrong")
    assert throttled.success is False
    assert "Too many attempts" in (throttled.error or "")

    # ...but the CORRECT password still wins on the very next call.
    good = login(_EMAIL, _PASSWORD)
    assert good.success is True


# --------------------------------------------------------------------------
# Property 2: after N failures the next FAILED attempt is throttled.
# --------------------------------------------------------------------------

def test_failed_attempts_are_throttled_past_threshold():
    signup(_EMAIL, _PASSWORD)

    # Up to and including the threshold, failures return the generic message.
    for _ in range(_BACKOFF_THRESHOLD):
        res = login(_EMAIL, "wrong-password")
        assert res.success is False
        assert res.error == "Invalid email or password."

    # The (threshold+1)-th failure crosses into throttle territory.
    throttled = login(_EMAIL, "wrong-password")
    assert throttled.success is False
    assert "Too many attempts" in (throttled.error or "")
    assert "try again in" in (throttled.error or "")


def test_backoff_grows_and_is_capped():
    # Pure-function check on the exponential-with-cap schedule.
    assert _backoff_seconds(_BACKOFF_THRESHOLD) == 0          # at threshold: no throttle
    assert _backoff_seconds(_BACKOFF_THRESHOLD + 1) == 2       # first throttle
    assert _backoff_seconds(_BACKOFF_THRESHOLD + 2) == 4
    assert _backoff_seconds(_BACKOFF_THRESHOLD + 3) == 8
    # Grows exponentially but is clamped at the 30s cap.
    assert _backoff_seconds(_BACKOFF_THRESHOLD + 50) == 30
    assert _backoff_seconds(1000) == 30


# --------------------------------------------------------------------------
# Property 3: a successful login resets the counter.
# --------------------------------------------------------------------------

def test_success_resets_counter_so_later_failure_is_not_throttled():
    signup(_EMAIL, _PASSWORD)

    # Rack up failures past the threshold, then log in successfully.
    _fail_n_times(_BACKOFF_THRESHOLD + 4)
    good = login(_EMAIL, _PASSWORD)
    assert good.success is True

    # Counter must be cleared in the DB.
    with get_session() as s:
        user = get_user_by_email(s, _EMAIL)
        assert user.failed_login_count == 0
        assert user.last_failed_login_at is None

    # A single fresh failure is therefore NOT throttled.
    res = login(_EMAIL, "wrong-again")
    assert res.success is False
    assert res.error == "Invalid email or password."


def test_unknown_email_never_throttles_or_creates_rows():
    # Hammering an unknown email must not create attacker-controlled rows and
    # must keep returning the generic failure (no per-email counter to grow).
    for _ in range(_BACKOFF_THRESHOLD + 5):
        res = login("ghost@example.com", "whatever")
        assert res.success is False
        assert res.error == "Invalid email or password."

    with get_session() as s:
        assert get_user_by_email(s, "ghost@example.com") is None
