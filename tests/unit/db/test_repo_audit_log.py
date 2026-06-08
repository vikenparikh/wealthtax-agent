"""Tests for the audit-log helpers in db/repo.py (write_audit, list_audit_for_user).

The audit trail records auth + return mutations; these pin that entries are
written and read back, that the listing is user-scoped (no cross-user leakage),
and that the limit is respected. Inherits the in-memory SQLite fixture from
tests/unit/db/conftest.py.
"""

from wealthtax_agent.db import get_session
from wealthtax_agent.db.repo import create_user, list_audit_for_user, write_audit


def _user(email):
    with get_session() as s:
        return create_user(s, email=email, hashed_password="h").id


def test_write_audit_then_list_returns_the_entry():
    uid = _user("a@example.com")
    with get_session() as s:
        write_audit(s, user_id=uid, return_id=None, action="login", payload={"ip": "1.2.3.4"})
    with get_session() as s:
        rows = list_audit_for_user(s, user_id=uid)
        assert len(rows) == 1
        assert rows[0].action == "login"
        assert rows[0].user_id == uid


def test_list_audit_is_user_scoped():
    a = _user("owner@example.com")
    b = _user("other@example.com")
    with get_session() as s:
        write_audit(s, user_id=a, return_id=None, action="signup", payload={})
    with get_session() as s:
        assert list_audit_for_user(s, user_id=b) == []        # no cross-user leakage
        assert len(list_audit_for_user(s, user_id=a)) == 1


def test_list_audit_returns_all_actions_for_a_user():
    uid = _user("multi@example.com")
    with get_session() as s:
        for action in ("signup", "login", "logout"):
            write_audit(s, user_id=uid, return_id=None, action=action, payload={})
    with get_session() as s:
        assert {r.action for r in list_audit_for_user(s, user_id=uid)} == {"signup", "login", "logout"}


def test_list_audit_respects_limit():
    uid = _user("busy@example.com")
    with get_session() as s:
        for i in range(5):
            write_audit(s, user_id=uid, return_id=None, action=f"event{i}", payload={})
    with get_session() as s:
        assert len(list_audit_for_user(s, user_id=uid, limit=3)) == 3
