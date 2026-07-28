"""After ``alembic upgrade head`` the users table has the backoff columns.

Pins migration ``9a3956f3584c`` — the two delay-not-lockout bookkeeping
columns must exist on ``users`` when migrations are run from scratch (the
Postgres/prod path; tests otherwise use ``create_all`` which already picks up
the model change). Mirrors the fixture style of
``test_taxreturn_encryption_migration.py``.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from wealthtax_agent.config import reset_settings_cache
from wealthtax_agent.db import reset_engine_cache

_FERNET_KEY = "8ZK4uF_jiBu3VqDOq6Mhs1aHCk7d8oxIvO34v9dW6X8="
_REPO_ROOT = Path(__file__).resolve().parents[3]
_ALEMBIC_INI = _REPO_ROOT / "alembic.ini"


@pytest.fixture
def fresh_db(monkeypatch):
    """Brand-new SQLite file, run alembic upgrade head, yield the URL."""
    db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_file.close()
    db_url = f"sqlite:///{db_file.name}"

    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("WEALTHTAX_FERNET_KEY", _FERNET_KEY)
    reset_settings_cache()
    reset_engine_cache()

    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
    command.upgrade(cfg, "head")

    yield db_url

    reset_engine_cache()
    reset_settings_cache()
    try:
        os.unlink(db_file.name)
    except OSError:
        pass


def test_backoff_columns_exist_after_upgrade(fresh_db):
    engine = sa.create_engine(fresh_db)
    inspector = sa.inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("users")}
    assert "failed_login_count" in cols, f"missing failed_login_count; got {cols}"
    assert "last_failed_login_at" in cols, f"missing last_failed_login_at; got {cols}"


def test_failed_login_count_defaults_to_zero(fresh_db):
    engine = sa.create_engine(fresh_db)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO users (id, email, hashed_password, created_at) "
                "VALUES ('u1', 'mig@example.com', 'x', '2026-01-01 00:00:00')"
            )
        )
        val = conn.execute(
            sa.text("SELECT failed_login_count FROM users WHERE id='u1'")
        ).scalar_one()
    assert val == 0
