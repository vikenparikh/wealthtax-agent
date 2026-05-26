# WealthTax Agent — Production-Ready PRD

**Branch:** `ralph/production-ready` (never force-push main)
**Baseline:** v0.5.0 · 478 tests passing · `37f7f9b`
**EXIT_SIGNAL:** Ralph stops when all acceptance criteria are green AND Claude emits `EXIT_SIGNAL`.

---

## Goal

Make WealthTax usable as a real tax-prep tool for CA / US / IN: hardened security posture, full
multi-step intake with persistence and re-edit, and a working UI that survives restarts.

## Constraints

- Do NOT touch `.claude/`. Push to `ralph/production-ready`; PR to main; never force-push main.
- TDD: pytest test before implementation for every new endpoint or engine path.
- LLM invariant preserved: LLMs never perform tax arithmetic.
- One logical change per commit (conventional commit format).
- Auth: Cloudflare Access email-gate is sufficient; do not build per-app auth.

---

## Work items

### S1 — Eliminate Groq PII exposure

No DPA with Groq; raw slip text (SIN/SSN/PAN) crosses a third-party boundary. Choose one:

- (a) Add `docs/groq-dpa-marker.md` confirming a signed DPA is on file, OR
- (b) Swap all LLM calls in `llm.py` to Anthropic SDK (`claude-haiku-3-5` for parse/classify/
  explain; `claude-3-5-sonnet` for OCR/vision). Replace `GROQ_API_KEY` with `ANTHROPIC_API_KEY`
  everywhere. Keep `LOCAL_OCR_ONLY=true` fallback.

**Test:** `tests/unit/test_llm_provider.py` — DPA marker exists OR no `groq` import remains.

### S2 — `transmissible=false` technical enforcement

Stamp is a JSON annotation; code has no guard against submission. Add
`assert artifact.transmissible is False` (raise `TransmissionBlockedError`) at every
`FilingArtifact` production site in `build_return.py` and `filing/*.py`.

**Test:** `tests/unit/test_transmission_guard.py` — `transmissible=True` path raises the error.

### S3 — Encrypt `TaxReturn.fields` at rest

`TaxReturn.fields` is plaintext JSON; Fernet is already a dep. Add `encrypt_json` /
`decrypt_json` in `db/crypto.py`. Wrap `TaxReturn.fields` with a SQLAlchemy `TypeDecorator`.
Alembic migration to re-encode existing rows.

**Test:** `tests/unit/db/test_taxreturn_encryption.py` — raw bytes != original JSON; round-trip
decrypts correctly.

### S4 — Verify and document password hashing

Hashing scheme unconfirmed in `auth.py`. Confirm or migrate to `bcrypt`/`argon2-cffi`.
Add `SECURITY.md` documenting scheme and work factor.

**Test:** `tests/unit/test_auth_hashing.py` — stored hash != plaintext; verify() returns True.

### S5 — Health check route

Launcher pings `/healthz`; Streamlit doesn't serve it. Add a FastAPI sidecar
(`src/wealthtax_agent/healthz.py`, port 8502) returning `{"status":"ok"}` on `GET /healthz`.
Wire as second service + healthcheck in `docker-compose*.yml`.

**Test:** `tests/unit/test_healthz.py` — `TestClient GET /healthz` returns 200.

### S6 — Multi-step intake with persistence

Current intake is a single expander; no guided flow, no mid-session save, no re-edit.

1. `intake/wizard.py` 5-step machine: (1) jurisdiction + year, (2) residency days, (3) income
   sources per jurisdiction, (4) deductions/credits, (5) review + submit.
2. Auto-save to `TaxReturn(status="draft")` on each Next click; survive restart.
3. Return History "Edit" button pre-populates wizard from stored (decrypted) fields.
4. Sidebar step indicator (1/5 … 5/5) with back/next.

**Tests:** `test_wizard_steps.py` (step transitions) + `test_intake_persistence.py` (draft
survives new DB session).

### S7 — Verify all three jurisdictions end-to-end

Fix any broken routes in the 8 golden cross-border scenarios. Add one new India-only scenario
(new regime, 80C, HRA) to close the gap.

**Test:** `tests/integration/scenarios/test_india_only_new_regime.py` — `DraftReturn.total_tax > 0`
and ITR JSON artifact generated.

### S8 — Landing + navigation + dashboard

1. Landing (`_render_landing()`) for unauthenticated / pre-login: product name, 3-bullet value
   prop, "Get started" button.
2. Top nav: Home | New Return | My Returns | Settings.
3. Dashboard (`_render_dashboard()`): return count, most recent return summary, CPA disclaimer.
4. All sections render without exception in `AppTest` for both modes.

**Test:** Extend `tests/integration/test_streamlit_smoke.py` to cover landing + dashboard.

---

## Acceptance criteria

- [ ] **AC1** — `pytest tests/unit/test_llm_provider.py` passes (Groq DPA marker OR Anthropic SDK only).
- [ ] **AC2** — `pytest tests/unit/test_transmission_guard.py` passes (`TransmissionBlockedError` raised).
- [ ] **AC3** — `pytest tests/unit/db/test_taxreturn_encryption.py` passes (fields not plaintext in SQLite).
- [ ] **AC4** — `pytest tests/unit/test_auth_hashing.py` passes (bcrypt/argon2 verified).
- [ ] **AC5** — `pytest tests/unit/test_healthz.py` passes (`GET /healthz` returns 200).
- [ ] **AC6** — `pytest tests/integration/test_intake_persistence.py` passes (draft survives restart).
- [ ] **AC7** — All 8 original + 1 new India-only scenario pass.
- [ ] **AC8** — Extended Streamlit smoke passes for landing, dashboard, nav in both modes.
- [ ] **AC9** — `pytest --no-cov -q` exits 0; total count >= 510.
- [ ] **AC10** — `docker compose up -d` healthcheck green within 30s.

## Out of scope

SOC 2 / PIPEDA certification, right-to-erasure, rate limiting / MFA, new jurisdictions, CPA audit.
