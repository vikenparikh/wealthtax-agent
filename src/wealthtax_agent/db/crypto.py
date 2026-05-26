"""Symmetric encryption for PII columns.

Uses Fernet (AES-128-CBC + HMAC) from ``cryptography``. The key comes from
``WEALTHTAX_FERNET_KEY``; helpers are pure functions so they can be unit
tested without touching the DB.

``EncryptedJSON`` is a SQLAlchemy ``TypeDecorator`` that transparently encrypts
a Python dict to Fernet ciphertext on write and decrypts it on read.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import LargeBinary
from sqlalchemy.types import TypeDecorator

from wealthtax_agent.config import get_settings


def _fernet() -> Fernet:
    return Fernet(get_settings().fernet_key.encode("utf-8"))


def encrypt(value: Optional[str]) -> Optional[bytes]:
    if value is None:
        return None
    return _fernet().encrypt(value.encode("utf-8"))


def decrypt(blob: Optional[bytes]) -> Optional[str]:
    if blob is None:
        return None
    try:
        return _fernet().decrypt(blob).decode("utf-8")
    except InvalidToken:
        return None


def encrypt_json(data: Optional[Dict[str, Any]]) -> Optional[bytes]:
    """Serialize *data* to JSON then Fernet-encrypt the result."""
    if data is None:
        return None
    return _fernet().encrypt(json.dumps(data, default=str).encode("utf-8"))


def decrypt_json(blob: Optional[bytes]) -> Optional[Dict[str, Any]]:
    """Decrypt Fernet ciphertext and deserialize as JSON."""
    if blob is None:
        return None
    try:
        plain = _fernet().decrypt(blob).decode("utf-8")
        return json.loads(plain)
    except (InvalidToken, json.JSONDecodeError):
        return None


class EncryptedJSON(TypeDecorator):
    """SQLAlchemy column type that stores a dict as Fernet-encrypted bytes.

    The raw column is ``LargeBinary``; Python consumers always see a plain dict
    (or ``None``).  The encryption key is read from ``WEALTHTAX_FERNET_KEY``
    at runtime so tests can rotate keys via monkeypatch / env.
    """

    impl = LargeBinary
    cache_ok = True

    def process_bind_param(self, value: Optional[Dict[str, Any]], dialect) -> Optional[bytes]:
        return encrypt_json(value)

    def process_result_value(self, value: Optional[bytes], dialect) -> Optional[Dict[str, Any]]:
        return decrypt_json(value)
