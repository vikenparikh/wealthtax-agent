"""SQLAlchemy session + engine factory.

The engine is built lazily from settings so tests can swap ``DATABASE_URL``
between cases. ``get_session()`` is the standard entry point — wrap it in a
``with`` block to ensure the session is closed.
"""

from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from wealthtax_agent.config import get_settings


Base = declarative_base()


@lru_cache(maxsize=1)
def _engine_and_factory():
    settings = get_settings()
    connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    engine = create_engine(settings.database_url, future=True, connect_args=connect_args)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return engine, SessionLocal


def get_engine():
    return _engine_and_factory()[0]


def get_session_factory():
    return _engine_and_factory()[1]


@contextmanager
def get_session() -> Iterator[Session]:
    Session_ = get_session_factory()
    session = Session_()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine_cache() -> None:
    """Used by tests after monkeypatching env vars."""
    _engine_and_factory.cache_clear()


def create_all_for_tests() -> None:
    """Convenience for unit tests using in-memory SQLite."""
    from wealthtax_agent.db import models  # noqa: F401 - register tables

    Base.metadata.create_all(bind=get_engine())
