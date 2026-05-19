"""Symmetric encryption for PII columns.

Uses Fernet (AES-128-CBC + HMAC) from ``cryptography``. The key comes from
``WEALTHTAX_FERNET_KEY``; helpers are pure functions so they can be unit
tested without touching the DB.
"""

from __future__ import annotations

from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

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
