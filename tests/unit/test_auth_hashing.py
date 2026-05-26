"""AC4 — Password hashing scheme verified (bcrypt, work factor >= 12).

Tests:
- Stored hash != plaintext password.
- verify() returns True for the correct password.
- verify() returns False for a wrong password.
- Hash is a valid bcrypt string ($2b$12$...).
- Constant-time verify doesn't raise on empty / long inputs.
- SECURITY.md exists and documents the scheme.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from wealthtax_agent.auth import hash_password, verify_password


REPO_ROOT = Path(__file__).resolve().parents[2]
SECURITY_MD = REPO_ROOT / "SECURITY.md"

_BCRYPT_PATTERN = re.compile(r"^\$2[ab]?\$(\d{2})\$[./A-Za-z0-9]{53}$")


def test_stored_hash_not_plaintext():
    pw = "super-secret-password-123"
    hashed = hash_password(pw)
    assert hashed != pw, "hash must differ from plaintext"
    assert pw not in hashed, "plaintext must not appear inside the hash string"


def test_verify_correct_password():
    pw = "correct-horse-battery-staple"
    hashed = hash_password(pw)
    assert verify_password(pw, hashed) is True


def test_verify_wrong_password():
    pw = "correct-horse-battery-staple"
    hashed = hash_password(pw)
    assert verify_password("wrong-password", hashed) is False


def test_hash_is_bcrypt_format():
    """Hash must match $2b$NN$ prefix with cost factor >= 12."""
    hashed = hash_password("any-password")
    m = _BCRYPT_PATTERN.match(hashed)
    assert m is not None, f"hash does not look like bcrypt: {hashed[:20]!r}"
    cost_factor = int(m.group(1))
    assert cost_factor >= 12, f"bcrypt cost factor {cost_factor} is below recommended minimum of 12"


def test_different_hashes_for_same_password():
    """bcrypt must generate a new salt each call."""
    pw = "same-password"
    h1 = hash_password(pw)
    h2 = hash_password(pw)
    assert h1 != h2, "bcrypt salts must differ between invocations"


def test_verify_empty_password_returns_false():
    hashed = hash_password("valid-password")
    # Should not raise; should just return False
    result = verify_password("", hashed)
    assert result is False


def test_verify_long_password_does_not_raise():
    """Inputs longer than 72 bytes must be handled (clamped) without error."""
    long_pw = "A" * 200
    hashed = hash_password(long_pw)
    assert verify_password(long_pw, hashed) is True


def test_security_md_exists_and_mentions_bcrypt():
    assert SECURITY_MD.exists(), (
        f"SECURITY.md not found at {SECURITY_MD}. "
        "Add it to document the password hashing scheme."
    )
    content = SECURITY_MD.read_text(encoding="utf-8")
    assert "bcrypt" in content.lower(), "SECURITY.md must document bcrypt usage"
    assert "work factor" in content.lower() or "rounds" in content.lower(), (
        "SECURITY.md must document the bcrypt work factor / round count"
    )
