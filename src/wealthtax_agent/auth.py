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
    touch_last_login,
    write_audit,
)
from wealthtax_agent.db.models import User


_BCRYPT_MAX = 72  # bcrypt errors above 72 bytes; clamp eagerly.


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
        if user is None or not verify_password(password, user.hashed_password):
            return AuthResult(success=False, error="Invalid email or password.")
        touch_last_login(session, user)
        sess = create_session(session, user_id=user.id)
        write_audit(session, user_id=user.id, return_id=None, action="login", payload={})
        return AuthResult(success=True, user_id=user.id, session_id=sess.id)


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
