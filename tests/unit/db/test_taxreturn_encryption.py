"""AC3 — TaxReturn.fields encrypted at rest.

Asserts:
- Raw bytes stored in SQLite != the original JSON string (not plaintext).
- Round-trip decrypt returns the original dict.
- None round-trips to None.
"""
from __future__ import annotations

import json

import pytest
import sqlalchemy as sa

from wealthtax_agent.config import reset_settings_cache
from wealthtax_agent.db import create_all_for_tests, get_engine, get_session, reset_engine_cache
from wealthtax_agent.db.models import TaxReturn, User


_FERNET_KEY = "8ZK4uF_jiBu3VqDOq6Mhs1aHCk7d8oxIvO34v9dW6X8="
_FIELDS_PAYLOAD = {
    "jurisdiction": "CA",
    "filing_year": 2024,
    "employment_income": 95000.0,
    "province": "ON",
}


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


def _make_user(session) -> User:
    u = User(
        email="enc-test@example.com",
        hashed_password="$2b$12$fakehashXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
    )
    session.add(u)
    session.flush()
    return u


def test_fields_not_plaintext_in_db():
    """Raw bytes in the DB must not equal the JSON string of the payload."""
    with get_session() as session:
        user = _make_user(session)
        tr = TaxReturn(
            user_id=user.id,
            filing_year=2024,
            jurisdictions_json=["CA"],
            fields=_FIELDS_PAYLOAD,
        )
        session.add(tr)
        session.flush()
        return_id = tr.id

    # Read raw bytes directly via SQLAlchemy Core (bypasses the TypeDecorator)
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT fields FROM tax_returns WHERE id = :id"),
            {"id": return_id},
        ).fetchone()

    raw_bytes = row[0]
    assert raw_bytes is not None, "fields column should not be NULL after writing a dict"

    # Could be bytes or str depending on SQLite driver; normalise
    if isinstance(raw_bytes, str):
        raw_bytes = raw_bytes.encode("utf-8")

    plain_json = json.dumps(_FIELDS_PAYLOAD, default=str).encode("utf-8")
    assert raw_bytes != plain_json, (
        "fields stored as plaintext — Fernet encryption is not applied"
    )
    # Confirm it looks like Fernet (starts with version byte gAA...)
    assert raw_bytes[:3] in (b"gAA", b"gAE"), (
        f"Expected Fernet ciphertext prefix, got: {raw_bytes[:8]!r}"
    )


def test_fields_round_trip():
    """ORM-level read must return the original dict after commit."""
    with get_session() as session:
        user = _make_user(session)
        tr = TaxReturn(
            user_id=user.id,
            filing_year=2024,
            jurisdictions_json=["CA"],
            fields=_FIELDS_PAYLOAD,
        )
        session.add(tr)
        session.flush()
        return_id = tr.id

    # Fresh session — forces decrypt path
    with get_session() as session:
        tr2 = session.get(TaxReturn, return_id)
        assert tr2 is not None
        assert tr2.fields == _FIELDS_PAYLOAD


def test_fields_none_round_trip():
    """None fields should store NULL and return None."""
    with get_session() as session:
        user = _make_user(session)
        tr = TaxReturn(
            user_id=user.id,
            filing_year=2024,
            jurisdictions_json=["US"],
            fields=None,
        )
        session.add(tr)
        session.flush()
        return_id = tr.id

    with get_session() as session:
        tr2 = session.get(TaxReturn, return_id)
        assert tr2.fields is None


def test_encrypt_json_helpers_directly():
    """Direct unit test for encrypt_json / decrypt_json helpers."""
    from wealthtax_agent.db.crypto import decrypt_json, encrypt_json

    blob = encrypt_json(_FIELDS_PAYLOAD)
    assert isinstance(blob, bytes)
    # Must not be plaintext
    assert b"employment_income" not in blob
    # Round-trip
    assert decrypt_json(blob) == _FIELDS_PAYLOAD


def test_decrypt_json_with_garbage_returns_none():
    from wealthtax_agent.db.crypto import decrypt_json

    assert decrypt_json(b"not-fernet-ciphertext") is None


def test_decrypt_json_none_returns_none():
    from wealthtax_agent.db.crypto import decrypt_json

    assert decrypt_json(None) is None
