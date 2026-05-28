"""P2-AC2 — TaxReturn mutation audit log.

Asserts:
- Every ``create`` / ``update`` / ``status_change`` on a ``TaxReturn`` appends a
  row to ``tax_return_events``.
- Each row carries ``user_id``, ``event_type``, ``timestamp``, ``before_hash``
  (sha256, None only for create), and ``after_hash`` (sha256).
- ``user_id`` is never NULL.
"""

from __future__ import annotations

from typing import List, Tuple

import pytest

from wealthtax_agent.config import reset_settings_cache
from wealthtax_agent.db import create_all_for_tests, get_session, reset_engine_cache
from wealthtax_agent.db.models import TaxReturn, TaxReturnEvent, User

_FERNET_KEY = "8ZK4uF_jiBu3VqDOq6Mhs1aHCk7d8oxIvO34v9dW6X8="


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("WEALTHTAX_FERNET_KEY", _FERNET_KEY)
    reset_settings_cache()
    reset_engine_cache()
    create_all_for_tests()
    yield
    reset_engine_cache()
    reset_settings_cache()


def _make_user(session, email: str = "audit@example.com") -> User:
    u = User(
        email=email,
        hashed_password="$2b$12$fakehashXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
    )
    session.add(u)
    session.flush()
    return u


def _snapshot_events(return_id: str) -> List[Tuple[str, str, str | None, str, object]]:
    """Read events and return plain tuples (event_type, user_id, before_hash,
    after_hash, timestamp) — avoids DetachedInstanceError after session close.
    """
    with get_session() as session:
        rows = (
            session.query(TaxReturnEvent)
            .filter(TaxReturnEvent.return_id == return_id)
            .order_by(TaxReturnEvent.timestamp.asc(), TaxReturnEvent.id.asc())
            .all()
        )
        return [
            (r.event_type, r.user_id, r.before_hash, r.after_hash, r.timestamp)
            for r in rows
        ]


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def test_create_emits_one_event_row():
    with get_session() as session:
        user = _make_user(session)
        user_id = user.id
        tr = TaxReturn(
            user_id=user.id,
            filing_year=2024,
            jurisdictions_json=["CA"],
            fields={"province": "ON"},
        )
        session.add(tr)
        session.flush()
        return_id = tr.id

    events = _snapshot_events(return_id)
    assert len(events) == 1
    event_type, ev_user, before, after, ts = events[0]
    assert event_type == "create"
    assert ev_user == user_id
    assert before is None
    assert after and len(after) == 64
    assert ts is not None


# ---------------------------------------------------------------------------
# Update (non-status mutation)
# ---------------------------------------------------------------------------


def test_field_update_emits_update_event_with_distinct_hashes():
    with get_session() as session:
        user = _make_user(session)
        tr = TaxReturn(
            user_id=user.id,
            filing_year=2024,
            jurisdictions_json=["CA"],
            fields={"province": "ON"},
        )
        session.add(tr)
        session.flush()
        return_id = tr.id

    with get_session() as session:
        tr = session.get(TaxReturn, return_id)
        tr.fields = {"province": "BC"}
        session.flush()

    events = _snapshot_events(return_id)
    assert [e[0] for e in events] == ["create", "update"]
    _, ev_user, before, after, _ = events[1]
    assert ev_user is not None
    assert before is not None
    assert after is not None
    assert before != after


# ---------------------------------------------------------------------------
# Status change
# ---------------------------------------------------------------------------


def test_status_mutation_emits_status_change_event():
    with get_session() as session:
        user = _make_user(session)
        tr = TaxReturn(
            user_id=user.id,
            filing_year=2024,
            jurisdictions_json=["CA"],
            status="draft",
        )
        session.add(tr)
        session.flush()
        return_id = tr.id

    with get_session() as session:
        tr = session.get(TaxReturn, return_id)
        tr.status = "submitted"
        session.flush()

    events = _snapshot_events(return_id)
    assert [e[0] for e in events] == ["create", "status_change"]
    _, ev_user, before, after, _ = events[1]
    assert ev_user is not None
    assert before is not None and after is not None
    assert before != after


# ---------------------------------------------------------------------------
# Mixed status + field change still classifies as status_change
# ---------------------------------------------------------------------------


def test_status_change_dominates_when_combined_with_field_edit():
    with get_session() as session:
        user = _make_user(session)
        tr = TaxReturn(
            user_id=user.id,
            filing_year=2024,
            jurisdictions_json=["CA"],
            status="draft",
            fields={"a": 1},
        )
        session.add(tr)
        session.flush()
        return_id = tr.id

    with get_session() as session:
        tr = session.get(TaxReturn, return_id)
        tr.status = "submitted"
        tr.fields = {"a": 2}
        session.flush()

    events = _snapshot_events(return_id)
    assert events[-1][0] == "status_change"


# ---------------------------------------------------------------------------
# Hashes are deterministic — same payload yields same hash
# ---------------------------------------------------------------------------


def test_identical_payloads_hash_to_same_after_hash():
    with get_session() as session:
        user_a = _make_user(session, email="hash-a@example.com")
        user_b = _make_user(session, email="hash-b@example.com")
        for user in (user_a, user_b):
            tr = TaxReturn(
                user_id=user.id,
                filing_year=2024,
                jurisdictions_json=["CA"],
                fields={"province": "ON"},
            )
            session.add(tr)
        session.flush()

    with get_session() as session:
        rows = (
            session.query(TaxReturnEvent)
            .filter(TaxReturnEvent.event_type == "create")
            .all()
        )
        hashes = [r.after_hash for r in rows]
    assert len(hashes) == 2
    assert hashes[0] == hashes[1]


# ---------------------------------------------------------------------------
# user_id may never be NULL
# ---------------------------------------------------------------------------


def test_user_id_is_never_null_in_event_rows():
    """Drive several mutations and assert every event row has a user_id."""
    with get_session() as session:
        user = _make_user(session)
        tr = TaxReturn(
            user_id=user.id,
            filing_year=2024,
            jurisdictions_json=["CA"],
            status="draft",
        )
        session.add(tr)
        session.flush()
        return_id = tr.id

    with get_session() as session:
        tr = session.get(TaxReturn, return_id)
        tr.fields = {"x": 1}
        session.flush()

    with get_session() as session:
        tr = session.get(TaxReturn, return_id)
        tr.status = "submitted"
        session.flush()

    with get_session() as session:
        rows = session.query(TaxReturnEvent).all()
        user_ids = [r.user_id for r in rows]
        event_types = [r.event_type for r in rows]
    assert user_ids, "expected audit events for create+update+status_change"
    for uid, et in zip(user_ids, event_types):
        assert uid is not None, f"tax_return_events.user_id is NULL for event_type={et}"


# ---------------------------------------------------------------------------
# No-op flushes do not emit spurious update rows
# ---------------------------------------------------------------------------


def test_noop_flush_does_not_emit_extra_event():
    with get_session() as session:
        user = _make_user(session)
        tr = TaxReturn(
            user_id=user.id,
            filing_year=2024,
            jurisdictions_json=["CA"],
            fields={"province": "ON"},
        )
        session.add(tr)
        session.flush()
        return_id = tr.id

    with get_session() as session:
        tr = session.get(TaxReturn, return_id)
        _ = tr.fields  # touch without changing
        session.flush()

    events = _snapshot_events(return_id)
    assert [e[0] for e in events] == ["create"]
