"""Shared DB fixtures: every test in this dir gets a clean in-memory SQLite."""

import os
import pytest

from wealthtax_agent.config import reset_settings_cache
from wealthtax_agent.db import create_all_for_tests, reset_engine_cache


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    # Ensure a stable fernet key per test so encrypt/decrypt round-trips.
    if "WEALTHTAX_FERNET_KEY" not in os.environ:
        from cryptography.fernet import Fernet
        monkeypatch.setenv("WEALTHTAX_FERNET_KEY", Fernet.generate_key().decode())
    reset_settings_cache()
    reset_engine_cache()
    create_all_for_tests()
    yield
    reset_settings_cache()
    reset_engine_cache()
