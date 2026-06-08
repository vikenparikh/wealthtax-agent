"""Tests for the SQLAlchemy session/engine factory (db/__init__.py).

The get_session context manager's commit-on-success / rollback-on-exception
semantics protect data integrity but were only exercised indirectly. Also
pins the lazy engine caching, reset_engine_cache invalidation, the sqlite
connect path, and create_all_for_tests idempotency. The autouse fixture in
tests/unit/db/conftest.py provides a clean in-memory SQLite per test.
"""

import pytest

from wealthtax_agent.db import (
    create_all_for_tests,
    get_engine,
    get_session,
    get_session_factory,
    reset_engine_cache,
)
from wealthtax_agent.db.repo import create_user, get_user_by_email


def test_engine_and_factory_are_cached_singletons():
    assert get_engine() is get_engine()
    assert get_session_factory() is get_session_factory()


def test_sqlite_engine_is_built_from_settings():
    assert get_engine().dialect.name == "sqlite"


def test_get_session_commits_on_success():
    with get_session() as s:
        create_user(s, email="commit@example.com", hashed_password="h")
    with get_session() as s:
        assert get_user_by_email(s, "commit@example.com") is not None


def test_get_session_rolls_back_on_exception():
    class Boom(RuntimeError):
        pass

    with pytest.raises(Boom):
        with get_session() as s:
            create_user(s, email="rollback@example.com", hashed_password="h")
            raise Boom("failure after the insert")

    # the insert must not have persisted (rolled back)
    with get_session() as s:
        assert get_user_by_email(s, "rollback@example.com") is None


def test_reset_engine_cache_rebuilds_the_engine():
    e1 = get_engine()
    reset_engine_cache()
    assert get_engine() is not e1


def test_create_all_for_tests_is_idempotent():
    # conftest already called it once; calling again must not raise.
    create_all_for_tests()
    create_all_for_tests()
