"""Authentication helpers: password hashing, signup, login, sessions.

Wraps ``passlib`` for bcrypt + the ``db.repo`` helpers so callers don't need
to know about SQLAlchemy directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import bcrypt

from wealthtax_agent.db import get_session
from wealthtax_agent.db.crypto import encrypt
from wealthtax_agent.db.repo import (
    create_session,
    create_user,
    delete_session,
    get_active_session,
    get_user_by_email,
    record_failed_login,
    recent_failed_login_count,
    reset_failed_logins,
    touch_last_login,
    write_audit,
)
from wealthtax_agent.db.models import User


_BCRYPT_MAX = 72  # bcrypt errors above 72 bytes; clamp eagerly.

# --- Brute-force backoff (delay-NOT-lockout) --------------------------------
# On a FINANCIAL app the overriding requirement is fail-open for legit users:
# the correct password ALWAYS logs in, and a successful login clears the
# counter. So we never hard-lock an account — an attacker cannot lock a victim
# out by spamming their email, and a legit user is never permanently blocked.
# Instead, once recent failures for an email exceed a small threshold, the
# *failed* response reports a capped, exponentially-growing "try again in Ns"
# delay. This turns bcrypt's ~100ms/attempt into a much steeper cost curve for
# an online brute-force without ever standing between a real user and success.
_BACKOFF_THRESHOLD = 5          # failures within the window before we throttle
_BACKOFF_WINDOW_MINUTES = 15    # rolling window; older failures decay away
_BACKOFF_BASE_SECONDS = 2       # first throttled attempt waits ~this long
_BACKOFF_MAX_SECONDS = 30       # hard cap so we never delay unreasonably


def _backoff_seconds(failure_count: int) -> int:
    """Exponential backoff (seconds) for ``failure_count`` recent failures, capped.

    Returns 0 while at/under the threshold (no throttle yet). Past the
    threshold it grows 2, 4, 8, ... but is clamped at ``_BACKOFF_MAX_SECONDS``.
    """
    if failure_count <= _BACKOFF_THRESHOLD:
        return 0
    over = failure_count - _BACKOFF_THRESHOLD
    delay = _BACKOFF_BASE_SECONDS * (2 ** (over - 1))
    return min(delay, _BACKOFF_MAX_SECONDS)


def _bcrypt_input(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX]


@dataclass
class AuthResult:
    success: bool
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    error: Optional[str] = None


@dataclass
class CurrentUser:
    """Detached projection of ``User`` safe to hold outside a DB session."""

    id: str
    email: str
    created_at: object  # datetime, kept loose to avoid an import here


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_bcrypt_input(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_bcrypt_input(password), hashed.encode("utf-8"))
    except Exception:
        return False


def signup(email: str, password: str, full_name: Optional[str] = None) -> AuthResult:
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return AuthResult(success=False, error="Enter a valid email address.")
    if len(password or "") < 8:
        return AuthResult(success=False, error="Password must be at least 8 characters.")

    with get_session() as session:
        if get_user_by_email(session, email) is not None:
            return AuthResult(success=False, error="An account with this email already exists.")
        user = create_user(
            session,
            email=email,
            hashed_password=hash_password(password),
            full_name_enc=encrypt(full_name) if full_name else None,
        )
        sess = create_session(session, user_id=user.id)
        write_audit(session, user_id=user.id, return_id=None, action="signup", payload={"email": email})
        return AuthResult(success=True, user_id=user.id, session_id=sess.id)


def login(email: str, password: str) -> AuthResult:
    email = (email or "").strip().lower()
    with get_session() as session:
        user = get_user_by_email(session, email)

        # Unknown email: cannot (and must not) create attacker-controlled rows,
        # so no per-email counter exists here — return the generic failure.
        if user is None:
            return AuthResult(success=False, error="Invalid email or password.")

        # Correct password ALWAYS wins — checked BEFORE any backoff so a legit
        # user is never blocked by prior failures. Success clears the counter.
        if verify_password(password, user.hashed_password):
            reset_failed_logins(session, user)
            touch_last_login(session, user)
            sess = create_session(session, user_id=user.id)
            write_audit(session, user_id=user.id, return_id=None, action="login", payload={})
            return AuthResult(success=True, user_id=user.id, session_id=sess.id)

        # Wrong password. Record the failure, then decide whether to throttle
        # the *failed* response based on the (now-updated) recent count.
        count = record_failed_login(session, user, window_minutes=_BACKOFF_WINDOW_MINUTES)
        delay = _backoff_seconds(count)
        if delay > 0:
            write_audit(
                session, user_id=user.id, return_id=None,
                action="login_throttled", payload={"recent_failures": count, "backoff_s": delay},
            )
            return AuthResult(
                success=False,
                error=f"Too many attempts — try again in {delay}s.",
            )
        return AuthResult(success=False, error="Invalid email or password.")


def logout(session_id: str) -> None:
    with get_session() as session:
        sess = get_active_session(session, session_id)
        if sess is not None:
            write_audit(session, user_id=sess.user_id, return_id=None, action="logout", payload={})
            delete_session(session, session_id)


def current_user_from_session(session_id: Optional[str]) -> Optional[CurrentUser]:
    if not session_id:
        return None
    with get_session() as session:
        sess = get_active_session(session, session_id)
        if sess is None:
            return None
        user = session.get(User, sess.user_id)
        if user is None:
            return None
        return CurrentUser(id=user.id, email=user.email, created_at=user.created_at)


def ensure_self_hosted_user() -> str:
    """In ``self_hosted`` mode auto-create a single owner account on first run.

    Returns the user id so the UI can drop straight into the working flow
    without a sign-in step.
    """
    email = "owner@self-hosted.local"
    with get_session() as session:
        user = get_user_by_email(session, email)
        if user is None:
            user = create_user(session, email=email, hashed_password=hash_password("self-hosted-no-password"))
        sess = create_session(session, user_id=user.id, ttl_minutes=24 * 60 * 365)
        return sess.id
