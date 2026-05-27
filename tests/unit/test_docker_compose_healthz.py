"""AC10 — healthz sidecar is wired into docker-compose.yml.

Parses the YAML and asserts:
- a 'healthz' service exists
- it exposes port 8502
- it has a healthcheck
"""
from __future__ import annotations

import pathlib

import yaml


_COMPOSE_PATH = pathlib.Path(__file__).parent.parent.parent / "docker-compose.yml"


def _services() -> dict:
    with _COMPOSE_PATH.open() as f:
        return yaml.safe_load(f).get("services", {})


class TestDockerComposeHealthzService:
    def test_healthz_service_present(self):
        assert "healthz" in _services(), "healthz service missing from docker-compose.yml"

    def test_healthz_port_8502(self):
        healthz = _services()["healthz"]
        ports = healthz.get("ports", [])
        assert any("8502" in str(p) for p in ports), "healthz must expose port 8502"

    def test_healthz_has_healthcheck(self):
        healthz = _services()["healthz"]
        assert "healthcheck" in healthz, "healthz service must declare a healthcheck"

    def test_healthz_healthcheck_tests_endpoint(self):
        hc = _services()["healthz"]["healthcheck"]
        test_cmd = " ".join(hc.get("test", []))
        assert "8502" in test_cmd or "/healthz" in test_cmd, (
            "healthcheck must probe /healthz or port 8502"
        )

    def test_app_service_still_present(self):
        assert "app" in _services(), "app service must still exist"

    def test_db_service_still_present(self):
        assert "db" in _services(), "db service must still exist"
