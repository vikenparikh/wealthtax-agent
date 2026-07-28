"""High-level data-access helpers.

Every helper is ``user_id``-scoped so the call site cannot accidentally read
or write a different user's data. This is the only module that should issue
SQLAlchemy queries outside of tests.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from wealthtax_agent.config import get_settings
from wealthtax_agent.db.models import (
    AuditLog,
    ClarificationAnswer,
    Correction,
    FormSnapshot,
    RateLimitBucket,
    ReturnRevision,
    TaxReturn,
    User,
    UserSession,
)


# ---------- User ----------

def get_user_by_email(session: Session, email: str) -> Optional[User]:
    return session.execute(select(User).where(User.email == email.lower())).scalar_one_or_none()


def create_user(session: Session, *, email: str, hashed_password: str, full_name_enc: Optional[bytes] = None) -> User:
    user = User(email=email.lower(), hashed_password=hashed_password, full_name_enc=full_name_enc)
    session.add(user)
    session.flush()
    return user


def touch_last_login(session: Session, user: User) -> None:
    user.last_login = datetime.utcnow()


# ---------- Login-failure backoff (delay-NOT-lockout) ----------
#
# These helpers back the email-scoped brute-force backoff in ``auth.login``.
# The design is deliberately fail-open: the counter only ever *delays* the
# failed-login response — it can never block a login that presents the correct
# password (``reset_failed_logins`` runs on every success). ``window_minutes``
# lets stale failures decay so a legit user who typo'd hours ago is not stuck
# in a throttled state.

def record_failed_login(session: Session, user: User, *, window_minutes: int) -> int:
    """Increment the per-user failed-login counter, decaying stale failures.

    If the last failure is older than ``window_minutes`` the counter restarts
    at 1 (the old failures are considered expired). Returns the new count.
    """
    now = datetime.utcnow()
    last = user.last_failed_login_at
    if last is not None and (now - last) <= timedelta(minutes=window_minutes):
        user.failed_login_count = (user.failed_login_count or 0) + 1
    else:
        user.failed_login_count = 1
    user.last_failed_login_at = now
    return user.failed_login_count


def reset_failed_logins(session: Session, user: User) -> None:
    """Clear the failed-login counter. Called on every SUCCESSFUL login."""
    user.failed_login_count = 0
    user.last_failed_login_at = None


def recent_failed_login_count(session: Session, user: User, *, window_minutes: int) -> int:
    """Return the failed-login count if still within the window, else 0.

    Read-only: does not mutate the user. Used to decide whether the *current*
    failed attempt should be throttled, honouring the same decay window.
    """
    last = user.last_failed_login_at
    if last is None:
        return 0
    if (datetime.utcnow() - last) > timedelta(minutes=window_minutes):
        return 0
    return user.failed_login_count or 0


# ---------- Sessions ----------

def create_session(session: Session, *, user_id: str, ttl_minutes: Optional[int] = None) -> UserSession:
    ttl = ttl_minutes or get_settings().session_ttl_minutes
    sess = UserSession(user_id=user_id, expires_at=datetime.utcnow() + timedelta(minutes=ttl))
    session.add(sess)
    session.flush()
    return sess


def get_active_session(session: Session, session_id: str) -> Optional[UserSession]:
    sess = session.get(UserSession, session_id)
    if sess is None:
        return None
    if sess.expires_at <= datetime.utcnow():
        return None
    return sess


def delete_session(session: Session, session_id: str) -> None:
    sess = session.get(UserSession, session_id)
    if sess is not None:
        session.delete(sess)


# ---------- Tax returns ----------

def list_user_returns(session: Session, user_id: str) -> List[TaxReturn]:
    return list(session.execute(
        select(TaxReturn).where(TaxReturn.user_id == user_id).order_by(TaxReturn.filing_year.desc())
    ).scalars())


def start_return(session: Session, *, user_id: str, filing_year: int, jurisdictions: List[str]) -> TaxReturn:
    ret = TaxReturn(user_id=user_id, filing_year=filing_year, jurisdictions_json=list(jurisdictions))
    session.add(ret)
    session.flush()
    return ret


def get_return(session: Session, *, user_id: str, return_id: str) -> Optional[TaxReturn]:
    ret = session.get(TaxReturn, return_id)
    if ret is None or ret.user_id != user_id:
        return None
    return ret


def find_return_for_year(session: Session, *, user_id: str, filing_year: int) -> Optional[TaxReturn]:
    return session.execute(
        select(TaxReturn).where(TaxReturn.user_id == user_id, TaxReturn.filing_year == filing_year)
        .order_by(TaxReturn.updated_at.desc())
    ).scalars().first()


# ---------- Revisions ----------

def save_revision(
    session: Session,
    *,
    user_id: str,
    return_id: str,
    state_json: Dict[str, Any],
    summary_totals_json: Dict[str, Any],
    form_snapshots: List[Dict[str, Any]],
    corrections: Optional[List[Dict[str, Any]]] = None,
) -> ReturnRevision:
    ret = get_return(session, user_id=user_id, return_id=return_id)
    if ret is None:
        raise ValueError(f"return {return_id} not owned by {user_id}")
    next_number = 1 + len(ret.revisions)
    revision = ReturnRevision(
        return_id=return_id,
        revision_number=next_number,
        state_json=state_json,
        summary_totals_json=summary_totals_json,
    )
    session.add(revision)
    session.flush()
    for snap in form_snapshots:
        session.add(FormSnapshot(revision_id=revision.id, **snap))
    for corr in corrections or []:
        session.add(Correction(revision_id=revision.id, **corr))
    ret.current_revision_id = revision.id
    ret.updated_at = datetime.utcnow()
    return revision


def latest_revision(session: Session, *, user_id: str, return_id: str) -> Optional[ReturnRevision]:
    ret = get_return(session, user_id=user_id, return_id=return_id)
    if ret is None or ret.current_revision_id is None:
        return None
    return session.get(ReturnRevision, ret.current_revision_id)


def list_revisions(session: Session, *, user_id: str, return_id: str) -> List[ReturnRevision]:
    ret = get_return(session, user_id=user_id, return_id=return_id)
    if ret is None:
        return []
    return sorted(ret.revisions, key=lambda r: r.revision_number)


def revert_to_revision(session: Session, *, user_id: str, return_id: str, revision_number: int) -> Optional[ReturnRevision]:
    """Mark a prior revision as the current one. New revisions appended after
    this point continue numbering monotonically; the reverted entries stay in
    history but are not the "current" pointer.
    """
    ret = get_return(session, user_id=user_id, return_id=return_id)
    if ret is None:
        return None
    target = next((r for r in ret.revisions if r.revision_number == revision_number), None)
    if target is None:
        return None
    ret.current_revision_id = target.id
    ret.updated_at = datetime.utcnow()
    return target


# ---------- Clarifications ----------

def upsert_clarification_answer(session: Session, *, return_id: str, question_id: str, value: str) -> None:
    existing = session.execute(
        select(ClarificationAnswer).where(
            ClarificationAnswer.return_id == return_id,
            ClarificationAnswer.question_id == question_id,
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(ClarificationAnswer(return_id=return_id, question_id=question_id, value=value))
    else:
        existing.value = value


def get_clarification_answers(session: Session, *, return_id: str) -> Dict[str, str]:
    rows = session.execute(
        select(ClarificationAnswer).where(ClarificationAnswer.return_id == return_id)
    ).scalars()
    return {row.question_id: row.value or "" for row in rows}


# ---------- Audit log ----------

def write_audit(session: Session, *, user_id: Optional[str], return_id: Optional[str], action: str, payload: Dict[str, Any]) -> None:
    session.add(AuditLog(user_id=user_id, return_id=return_id, action=action, payload_json=payload))


def list_audit_for_user(session: Session, *, user_id: str, limit: int = 200) -> List[AuditLog]:
    return list(session.execute(
        select(AuditLog).where(AuditLog.user_id == user_id).order_by(AuditLog.created_at.desc()).limit(limit)
    ).scalars())


# ---------- Rate limiting ----------

def consume_rate_token(session: Session, *, user_id: str, bucket: str, max_per_minute: int) -> bool:
    """Token bucket. Returns True if a token was consumed, False if throttled."""
    row = session.get(RateLimitBucket, (user_id, bucket))
    now = datetime.utcnow()
    if row is None:
        row = RateLimitBucket(user_id=user_id, bucket=bucket, tokens=max_per_minute - 1, last_refill=now)
        session.add(row)
        return True
    elapsed = (now - row.last_refill).total_seconds()
    refill = int(elapsed / 60.0 * max_per_minute)
    if refill > 0:
        row.tokens = min(max_per_minute, row.tokens + refill)
        row.last_refill = now
    if row.tokens <= 0:
        return False
    row.tokens -= 1
    return True
