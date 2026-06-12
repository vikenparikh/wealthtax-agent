"""Centralised app configuration via environment variables.

Used everywhere we need a DB URL, encryption key, mode, etc. Keeping it in
one place means tests can monkeypatch a single function (``get_settings``)
instead of chasing env vars across modules.

Parsing is deliberately resilient: a malformed numeric env var or an
unknown mode falls back to the documented default instead of crashing app
boot, mirroring the last-resort ``_generate_dev_fernet_key`` behaviour.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from wealthtax_agent.logging_utils import get_logger

_log = get_logger("wealthtax_agent.config")

_VALID_MODES = {"saas", "self_hosted"}


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


def _int_env(name: str, default: int, minimum: int = 1) -> int:
    """Parse a positive-int env var, falling back to ``default`` on a bad value.

    A malformed ``SESSION_TTL_MINUTES`` / ``CORRECTION_RATE_PER_MINUTE`` (e.g.
    ``"30m"``) must not crash boot with an opaque ValueError. Non-positive
    values are also rejected, since both settings are durations/rates that
    only make sense as positive integers.
    """
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        _log.warning("config_invalid_int", extra={"var": name, "value": raw, "fallback": default})
        return default
    if value < minimum:
        _log.warning(
            "config_int_below_min",
            extra={"var": name, "value": value, "minimum": minimum, "fallback": default},
        )
        return default
    return value


def _mode_env(default: str = "self_hosted") -> str:
    """Normalise + validate WEALTHTAX_MODE; unknown modes fall back to default."""
    mode = os.getenv("WEALTHTAX_MODE", default).strip().lower()
    if mode not in _VALID_MODES:
        _log.warning("config_invalid_mode", extra={"value": mode, "fallback": default})
        return default
    return mode


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        database_url=os.getenv("DATABASE_URL", "sqlite:///./wealthtax.db"),
        fernet_key=os.getenv("WEALTHTAX_FERNET_KEY") or _generate_dev_fernet_key(),
        mode=_mode_env(),
        session_ttl_minutes=_int_env("SESSION_TTL_MINUTES", 1440),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        correction_rate_per_minute=_int_env("CORRECTION_RATE_PER_MINUTE", 20),
    )


def reset_settings_cache() -> None:
    """Used by tests after monkeypatching env vars."""
    get_settings.cache_clear()
