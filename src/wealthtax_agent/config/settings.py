"""Centralised app configuration via environment variables.

Used everywhere we need a DB URL, encryption key, mode, etc. Keeping it in
one place means tests can monkeypatch a single function (``get_settings``)
instead of chasing env vars across modules.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    database_url: str
    fernet_key: str
    mode: str  # "saas" or "self_hosted"
    session_ttl_minutes: int
    log_level: str
    correction_rate_per_minute: int


def _generate_dev_fernet_key() -> str:
    """Last-resort dev key so the app boots without crashing."""
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode("utf-8")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        database_url=os.getenv("DATABASE_URL", "sqlite:///./wealthtax.db"),
        fernet_key=os.getenv("WEALTHTAX_FERNET_KEY") or _generate_dev_fernet_key(),
        mode=os.getenv("WEALTHTAX_MODE", "self_hosted").strip().lower(),
        session_ttl_minutes=int(os.getenv("SESSION_TTL_MINUTES", "1440")),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        correction_rate_per_minute=int(os.getenv("CORRECTION_RATE_PER_MINUTE", "20")),
    )


def reset_settings_cache() -> None:
    """Used by tests after monkeypatching env vars."""
    get_settings.cache_clear()
