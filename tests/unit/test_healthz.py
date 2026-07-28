"""GET /healthz (liveness) + GET /readyz (readiness) on the health sidecar."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import wealthtax_agent.db as db
from wealthtax_agent.config import reset_settings_cache
from wealthtax_agent.db import create_all_for_tests, reset_engine_cache
from wealthtax_agent.healthz import app

client = TestClient(app)

# A structurally valid Fernet key (same one the db tests use).
_VALID_FERNET = "8ZK4uF_jiBu3VqDOq6Mhs1aHCk7d8oxIvO34v9dW6X8="


def test_healthz_returns_200():
    response = client.get("/healthz")
    assert response.status_code == 200


def test_healthz_returns_ok_payload():
    response = client.get("/healthz")
    assert response.json() == {"status": "ok"}


def test_healthz_content_type_is_json():
    response = client.get("/healthz")
    assert "application/json" in response.headers["content-type"]


# --- /readyz readiness probe ------------------------------------------------


@pytest.fixture
def _healthy_env(monkeypatch):
    """A reachable in-memory DB + a valid Fernet key — the ready baseline."""
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("WEALTHTAX_FERNET_KEY", _VALID_FERNET)
    reset_settings_cache()
    reset_engine_cache()
    create_all_for_tests()
    yield
    reset_engine_cache()
    reset_settings_cache()


def test_readyz_returns_200_when_db_and_config_ok(_healthy_env):
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"database": "ok", "config": "ok"},
    }


def test_readyz_returns_503_when_database_unavailable(_healthy_env, monkeypatch):
    # _check_database imports get_session from wealthtax_agent.db at call time,
    # so patching it there makes the DB probe raise -> readiness must fail.
    def _boom(*_a, **_k):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(db, "get_session", _boom)

    response = client.get("/readyz")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["database"].startswith("unavailable")
    assert body["checks"]["config"] == "ok"  # config still fine


def test_readyz_returns_503_when_fernet_key_invalid(_healthy_env, monkeypatch):
    # A malformed key would let the app boot but fail every PII decrypt.
    monkeypatch.setenv("WEALTHTAX_FERNET_KEY", "not-a-valid-fernet-key")
    reset_settings_cache()

    response = client.get("/readyz")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["config"].startswith("invalid")
    assert body["checks"]["database"] == "ok"  # DB still reachable


def test_readyz_reports_both_failures(monkeypatch):
    # No DB env + bad key: both checks fail, still a single 503 with breakdown.
    monkeypatch.setenv("WEALTHTAX_FERNET_KEY", "not-a-valid-fernet-key")
    reset_settings_cache()

    def _boom(*_a, **_k):
        raise RuntimeError("no engine")

    monkeypatch.setattr(db, "get_session", _boom)

    response = client.get("/readyz")
    assert response.status_code == 503
    checks = response.json()["checks"]
    assert checks["database"].startswith("unavailable")
    assert checks["config"].startswith("invalid")
