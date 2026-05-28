"""P2-AC1 — after ``alembic upgrade head`` every ``tax_returns.fields`` row
holds Fernet ciphertext (not valid JSON).

Asserts:
- Running migrations from scratch into a fresh SQLite DB creates the
  ``tax_returns.fields`` column.
- Rows written via the SQLAlchemy ORM are stored as Fernet ciphertext.
- ``SELECT fields FROM tax_returns LIMIT 1`` returns bytes that are *not*
  valid JSON.
- Any pre-existing plaintext-JSON row is re-encrypted by the migration
  data-migration step.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from wealthtax_agent.config import reset_settings_cache
from wealthtax_agent.db import get_session, reset_engine_cache
from wealthtax_agent.db.models import TaxReturn, User

_FERNET_KEY = "8ZK4uF_jiBu3VqDOq6Mhs1aHCk7d8oxIvO34v9dW6X8="
_REPO_ROOT = Path(__file__).resolve().parents[3]
_ALEMBIC_INI = _REPO_ROOT / "alembic.ini"


@pytest.fixture
def fresh_db(monkeypatch):
    """Spin up a brand-new SQLite file, run alembic upgrade head, then yield."""
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


def _make_user_and_return(payload: dict, email: str = "mig@example.com") -> tuple[str, str]:
    with get_session() as session:
        user = User(
            email=email,
            hashed_password="$2b$12$fakehashXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
        )
        session.add(user)
        session.flush()
        tr = TaxReturn(
            user_id=user.id,
            filing_year=2024,
            jurisdictions_json=["CA"],
            fields=payload,
        )
        session.add(tr)
        session.flush()
        return user.id, tr.id


# ---------------------------------------------------------------------------
# Schema shape after alembic upgrade head
# ---------------------------------------------------------------------------


def test_tax_returns_fields_column_exists_after_upgrade(fresh_db):
    engine = sa.create_engine(fresh_db)
    inspector = sa.inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("tax_returns")}
    assert "fields" in cols, f"expected 'fields' column on tax_returns, got {cols}"


def test_tax_return_events_table_exists_after_upgrade(fresh_db):
    engine = sa.create_engine(fresh_db)
    inspector = sa.inspect(engine)
    assert inspector.has_table("tax_return_events")
    cols = {c["name"] for c in inspector.get_columns("tax_return_events")}
    assert {"user_id", "return_id", "event_type", "timestamp",
            "before_hash", "after_hash"} <= cols


# ---------------------------------------------------------------------------
# Raw bytes invariant — must not be valid JSON
# ---------------------------------------------------------------------------


def test_fields_bytes_are_fernet_not_plaintext_json(fresh_db):
    payload = {"province": "ON", "income": 95_000.0}
    _make_user_and_return(payload)

    engine = sa.create_engine(fresh_db)
    with engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT fields FROM tax_returns LIMIT 1")
        ).fetchone()

    raw = row[0]
    assert raw is not None, "fields should not be NULL after writing a dict"
    if isinstance(raw, str):
        raw = raw.encode("utf-8")

    # 1) Must not equal the plaintext JSON bytes.
    plain = json.dumps(payload, default=str).encode("utf-8")
    assert raw != plain, "fields stored as plaintext JSON — encryption broken"

    # 2) Must not parse as JSON at all.
    with pytest.raises((ValueError, TypeError, UnicodeDecodeError)):
        json.loads(raw)

    # 3) Must look like a Fernet token.
    assert raw[:3] in (b"gAA", b"gAE"), (
        f"expected Fernet ciphertext prefix, got {raw[:8]!r}"
    )


def test_all_rows_after_upgrade_are_non_plaintext(fresh_db):
    """Bulk variant: insert several rows, scan every row, none parse as JSON."""
    for i in range(5):
        _make_user_and_return({"i": i, "x": "y" * 50}, email=f"bulk-{i}@example.com")

    engine = sa.create_engine(fresh_db)
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text("SELECT id, fields FROM tax_returns")
        ).fetchall()

    assert len(rows) == 5
    for row_id, raw in rows:
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        with pytest.raises((ValueError, TypeError, UnicodeDecodeError)):
            json.loads(raw)
        assert raw[:3] in (b"gAA", b"gAE"), f"row {row_id} not Fernet-encrypted"


def test_decryption_round_trips_through_orm(fresh_db):
    """End-to-end: the ORM-side decryption returns the original dict."""
    payload = {"province": "QC", "rrsp_room": 17_500.0}
    _, return_id = _make_user_and_return(payload)

    with get_session() as session:
        tr = session.get(TaxReturn, return_id)
        assert tr is not None
        assert tr.fields == payload


# ---------------------------------------------------------------------------
# Data migration — pre-existing plaintext row gets re-encrypted
# ---------------------------------------------------------------------------


def test_plaintext_row_is_reencrypted_by_data_migration_step(fresh_db):
    """Simulate a legacy DB: write a plaintext-JSON blob into fields, then
    invoke the migration's data-migration helper directly and assert the
    row was encrypted in place. (Alembic won't re-run a completed revision
    on its own; the helper is the unit-testable contract.)
    """
    engine = sa.create_engine(fresh_db)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO users (id, email, hashed_password, created_at) "
                "VALUES ('u-legacy', 'legacy@example.com', 'hp', CURRENT_TIMESTAMP)"
            )
        )
        plaintext = json.dumps({"legacy": True, "province": "ON"}).encode("utf-8")
        conn.execute(
            sa.text(
                "INSERT INTO tax_returns "
                "(id, user_id, filing_year, jurisdictions_json, status, "
                " created_at, updated_at, fields) "
                "VALUES ('r-legacy', 'u-legacy', 2024, '[\"CA\"]', 'draft', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, :fields)"
            ),
            {"fields": plaintext},
        )

    # Load the migration module and invoke its data-migration helper.
    import importlib.util

    mig_path = (
        _REPO_ROOT / "alembic" / "versions"
        / "e2f8a9c1b3d4_taxreturn_fields_and_audit_log.py"
    )
    spec = importlib.util.spec_from_file_location("mig_e2f8a9c1b3d4", mig_path)
    mig = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mig)

    with engine.begin() as conn:
        mig._encrypt_plaintext_rows(conn)

    with engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT fields FROM tax_returns WHERE id = 'r-legacy'")
        ).fetchone()
    raw = row[0]
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    assert raw[:3] in (b"gAA", b"gAE"), (
        f"legacy plaintext row was not re-encrypted: {raw[:16]!r}"
    )
    with pytest.raises((ValueError, TypeError, UnicodeDecodeError)):
        json.loads(raw)
