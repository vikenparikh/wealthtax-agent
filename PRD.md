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

---

## Acceptance criteria — Phase 2 (overnight)

- [ ] **P2-AC1** — Run `pytest tests/unit/db/test_taxreturn_encryption_migration.py` and assert all rows in the `tax_returns` table have non-plaintext `fields` bytes after `alembic upgrade head`; verify `SELECT fields FROM tax_returns LIMIT 1` via SQLite shell is not valid JSON.

- [ ] **P2-AC2** — Run `pytest tests/unit/db/test_tax_return_events.py` and assert every `TaxReturn` state mutation (`create`, `update`, `status_change`) appends a row to `tax_return_events` containing `user_id`, `event_type`, `timestamp`, `before_hash` (sha256), and `after_hash` (sha256); no row may have `user_id = NULL`.

- [ ] **P2-AC3** — Run `pytest tests/unit/test_review_report_pdf.py` and assert that calling `build_review_report_pdf(draft_return)` for each of CA / US / IN returns a `bytes` object whose first four bytes are `%PDF`; verify jurisdiction-specific fields appear (T1 line item for CA, Schedule 1 label for US, ITR section header for IN).

- [ ] **P2-AC4** — Run `pytest tests/unit/test_multi_year_carry_forward.py` and assert that `load_prior_year_defaults(user_id, year - 1)` returns a dict with at least `rrsp_room`, `capital_loss_carryforward`, and `foreign_tax_credits` populated from the previous `TaxReturn`; wizard step 3 pre-fills those values without overwriting any field the user has already typed.

- [ ] **P2-AC5** — Run `pytest tests/unit/engines/test_property_tax_inputs.py` and assert that CA engine accepts `property_tax_paid` (max credit: $12,000 CA), and US engine accepts `state_local_property_tax` (capped at $10,000 SALT); both inputs propagate to the corresponding `DraftReturn` line items and the deduction is reflected in `total_tax`.

- [ ] **P2-AC6** — Run `pytest tests/unit/test_wizard_tooltips.py` and assert that calling `load_tooltip(jurisdiction, field_key)` for at least 10 canonical fields (e.g. `ca.rrsp_contribution`, `us.foreign_tax_credit`, `in.hra_exemption`) returns a non-empty string loaded from `src/wealthtax_agent/content/tooltips/{jurisdiction}.md`; the markdown file must exist on disk.

- [ ] **P2-AC7** — Run `pytest tests/unit/test_groq_rate_limit.py` and assert that a simulated burst of 61 Groq calls within one hour for the same `user_id` raises `RateLimitExceeded` on the 61st call; confirm the counter resets after a mocked 3600-second window; no actual Groq network call is made (LLM is mocked at module level).

- [ ] **P2-AC8** — Run `pytest tests/unit/test_structured_logging.py` and assert that all log records emitted by `llm.py`, `graph.py`, and `build_return.py` are valid JSON (parse with `json.loads`); assert no record contains a string matching the regex `\b\d{3}-\d{2}-\d{4}\b` (SSN-shaped), `\b\d{9}\b` (SIN-shaped), or `\b[A-Z]{5}\d{4}[A-Z]\b` (PAN-shaped).

- [ ] **P2-AC9** — Run `pytest tests/integration/test_e2e_wizard_flow.py` and assert that a pytest fixture walks steps 1-5 of the wizard via `AppTest`, submitting valid data at each step, and the final `GraphState` contains `draft_return` with `total_tax > 0` and at least one filing artifact per selected jurisdiction; the fixture uses `WEALTHTAX_MODE=self_hosted` and `GROQ_API_KEY=gsk-test-key` with the LLM mocked.

- [ ] **P2-AC10** — Run `pytest tests/integration/test_streamlit_smoke.py -k cache` (new test class) and assert that calling the review-report render function twice with the same `DraftReturn` results in exactly one call to the underlying engine compute function; confirm with a `unittest.mock.patch` call count assert (`call_count == 1`).

- [ ] **P2-AC11** — Run `python -m pytest tests/unit/test_wizard_tooltips.py --co -q` and confirm no test requires a `GROQ_API_KEY` or `ANTHROPIC_API_KEY` env var; `load_tooltip` must be purely file-based with no external calls.

- [ ] **P2-AC12** — Run `bash scripts/check_tab_order.sh` (script reads the wizard form field definitions from `intake/wizard.py` and asserts they appear in logical DOM order: jurisdiction before year, income before deductions, deductions before review); script exits 0 when order is correct and exits 1 with a diff when a field is out of sequence.

- [ ] **P2-AC13** — Run `pytest --no-cov -q` and confirm total passing count is >= 545 (Phase 1 baseline ~530 + at least 15 new Phase 2 tests); zero failures, zero errors.

---

## Ralph guardrails for Phase 2

```text
- Push to `ralph/phase-2`, NEVER force-push main
- TaxReturn.fields encryption stays — no plaintext writes
- LLM never does arithmetic — preserve
- TDD per AC, one AC per commit
- EXIT_SIGNAL when all Phase 2 ACs pass
```
