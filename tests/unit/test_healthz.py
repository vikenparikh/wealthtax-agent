"""AC5 — GET /healthz returns 200 with {"status": "ok"}."""
from __future__ import annotations

from fastapi.testclient import TestClient

from wealthtax_agent.healthz import app

client = TestClient(app)


def test_healthz_returns_200():
    response = client.get("/healthz")
    assert response.status_code == 200


def test_healthz_returns_ok_payload():
    response = client.get("/healthz")
    assert response.json() == {"status": "ok"}


def test_healthz_content_type_is_json():
    response = client.get("/healthz")
    assert "application/json" in response.headers["content-type"]
