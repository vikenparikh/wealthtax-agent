"""Minimal FastAPI sidecar exposing GET /healthz on port 8502.

Separated from the main Streamlit app so orchestrators (docker-compose
healthcheck, Cloudflare Zero Trust, uptime monitors) can probe liveness
without loading the full LangGraph pipeline.

Usage (standalone):
    uvicorn wealthtax_agent.healthz:app --host 0.0.0.0 --port 8502
"""
from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="WealthTax Health Sidecar", docs_url=None, redoc_url=None)


@app.get("/healthz")
def healthz() -> dict:
    """Return 200 OK when the process is alive."""
    return {"status": "ok"}
