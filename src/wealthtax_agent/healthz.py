"""Minimal FastAPI sidecar exposing GET /healthz and GET /readyz on port 8502.

Separated from the main Streamlit app so orchestrators (docker-compose
healthcheck, Cloudflare Zero Trust, uptime monitors) can probe liveness AND
readiness without loading the full LangGraph pipeline.

- ``/healthz`` (liveness): 200 whenever the process is alive. Never touches
  dependencies, so it stays green during a transient DB blip — restarting the
  container on a liveness failure would be counterproductive there.
- ``/readyz`` (readiness): 200 only when the app can actually serve — the
  database is reachable and the Fernet key (which encrypts all PII at rest) is
  valid. Returns 503 with a per-check breakdown otherwise, so a load balancer
  can drain an instance that is alive but not serviceable.

Usage (standalone):
    uvicorn wealthtax_agent.healthz:app --host 0.0.0.0 --port 8502
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="WealthTax Health Sidecar", docs_url=None, redoc_url=None)


@app.get("/healthz")
def healthz() -> dict:
    """Return 200 OK when the process is alive (liveness — no dependency I/O)."""
    return {"status": "ok"}


def _check_database() -> tuple[bool, str]:
    """True + 'ok' when a trivial query succeeds against the configured DB."""
    try:
        from sqlalchemy import text

        from wealthtax_agent.db import get_session

        with get_session() as session:
            session.execute(text("SELECT 1"))
        return True, "ok"
    except Exception as exc:  # noqa: BLE001 - report, never surface a false 200
        return False, f"unavailable: {type(exc).__name__}"


def _check_config() -> tuple[bool, str]:
    """True + 'ok' when the configured Fernet key is structurally valid.

    A malformed WEALTHTAX_FERNET_KEY would let the app boot but fail every
    PII encrypt/decrypt at runtime, so readiness must reject it up front.
    """
    try:
        from cryptography.fernet import Fernet

        from wealthtax_agent.config import get_settings

        Fernet(get_settings().fernet_key.encode("utf-8"))
        return True, "ok"
    except Exception as exc:  # noqa: BLE001
        return False, f"invalid: {type(exc).__name__}"


@app.get("/readyz")
def readyz() -> JSONResponse:
    """200 only when every dependency check passes; else 503 with the breakdown."""
    db_ok, db_detail = _check_database()
    cfg_ok, cfg_detail = _check_config()
    ready = db_ok and cfg_ok
    body = {
        "status": "ready" if ready else "not_ready",
        "checks": {"database": db_detail, "config": cfg_detail},
    }
    return JSONResponse(status_code=200 if ready else 503, content=body)
