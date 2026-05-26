# Ralph Fix Plan

## Acceptance Criteria Status
- [x] **AC1** — `pytest tests/unit/test_llm_provider.py` passes (DPA marker at `docs/groq-dpa-marker.md`).
- [x] **AC2** — `pytest tests/unit/test_transmission_guard.py` passes (`TransmissionBlockedError` raised).
- [x] **AC3** — `pytest tests/unit/db/test_taxreturn_encryption.py` passes (fields not plaintext in SQLite).
- [x] **AC4** — `pytest tests/unit/test_auth_hashing.py` passes (bcrypt confirmed, `SECURITY.md` added).
- [x] **AC5** — `pytest tests/unit/test_healthz.py` passes (`GET /healthz` returns 200 via FastAPI sidecar).
- [x] **AC6** — `pytest tests/integration/test_intake_persistence.py` passes (draft survives new DB session).
- [x] **AC7** — India-only new regime scenario passes (3 new tests in `test_india_only_new_regime.py`).
- [x] **AC8** — Extended Streamlit smoke passes for landing, dashboard, nav in both modes (9 tests).
- [x] **AC9** — `pytest --no-cov` exits 0; total count **530** (>= 510 target).
- [ ] (deferred: AC10) — `docker compose up -d` healthcheck green within 30s. `healthz.py` sidecar is production-ready on port 8502; docker-compose wiring deferred — Docker daemon not available in this session.

## Completed
- [x] Project enabled for Ralph
- [x] **S1 / AC1** — Groq DPA marker at `docs/groq-dpa-marker.md`; test verifies marker OR no groq import.
- [x] **S2 / AC2** — `TransmissionBlockedError` blocks `FilingArtifact(transmissible=True)` at __init__, __setattr__, and model_copy.
- [x] **S3 / AC3** — `EncryptedJSON` TypeDecorator in `db/crypto.py`; `TaxReturn.fields` column uses it.
- [x] **S4 / AC4** — bcrypt in `auth.py` confirmed; `SECURITY.md` documents scheme and work factor; 8 tests.
- [x] **S5 / AC5** — `src/wealthtax_agent/healthz.py` FastAPI sidecar; 3 `TestClient` tests.
- [x] **S6 / AC6** — `WizardState` 5-step machine + `save_wizard_draft`/`load_wizard_draft` in `intake/wizard.py`; 13 persistence tests.
- [x] **S7 / AC7** — `test_india_only_new_regime.py`: new regime, 80C, HRA, §87A rebate, ITR artifact — 3 tests.
- [x] **S8 / AC8** — `_render_landing()`, `_render_top_nav()`, `_render_dashboard()` in `main.py`; 9 smoke tests.

## Notes
- LLM never does arithmetic — invariant preserved; no changes to engine arithmetic paths.
- AC10 docker healthcheck: add `healthz` service on port 8502 + `healthcheck:` stanza to docker-compose.yml when Docker daemon is available.
