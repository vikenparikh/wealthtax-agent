# Ralph Fix Plan

## High Priority
- [ ] **AC1** — `pytest tests/unit/test_llm_provider.py` passes (Groq DPA marker OR Anthropic SDK only).
- [x] **AC2** — `pytest tests/unit/test_transmission_guard.py` passes (`TransmissionBlockedError` raised).
- [ ] **AC3** — `pytest tests/unit/db/test_taxreturn_encryption.py` passes (fields not plaintext in SQLite).
- [ ] **AC4** — `pytest tests/unit/test_auth_hashing.py` passes (bcrypt/argon2 verified).
- [ ] **AC5** — `pytest tests/unit/test_healthz.py` passes (`GET /healthz` returns 200).
- [ ] **AC6** — `pytest tests/integration/test_intake_persistence.py` passes (draft survives restart).
- [ ] **AC7** — All 8 original + 1 new India-only scenario pass.
- [ ] **AC8** — Extended Streamlit smoke passes for landing, dashboard, nav in both modes.
- [ ] **AC9** — `pytest --no-cov -q` exits 0; total count >= 510.
- [ ] **AC10** — `docker compose up -d` healthcheck green within 30s.
- [ ] **P2-AC1** — Run `pytest tests/unit/db/test_taxreturn_encryption_migration.py` and assert all rows in the `tax_returns` table have non-plaintext `fields` bytes after `alembic upgrade head`; verify `SELECT fields FROM tax_returns LIMIT 1` via SQLite shell is not valid JSON.
- [ ] **P2-AC2** — Run `pytest tests/unit/db/test_tax_return_events.py` and assert every `TaxReturn` state mutation (`create`, `update`, `status_change`) appends a row to `tax_return_events` containing `user_id`, `event_type`, `timestamp`, `before_hash` (sha256), and `after_hash` (sha256); no row may have `user_id = NULL`.
- [x] **P2-AC3** — Run `pytest tests/unit/test_review_report_pdf.py` and assert that calling `build_review_report_pdf(draft_return)` for each of CA / US / IN returns a `bytes` object whose first four bytes are `%PDF`; verify jurisdiction-specific fields appear (T1 line item for CA, Schedule 1 label for US, ITR section header for IN).
- [ ] **P2-AC4** — Run `pytest tests/unit/test_multi_year_carry_forward.py` and assert that `load_prior_year_defaults(user_id, year - 1)` returns a dict with at least `rrsp_room`, `capital_loss_carryforward`, and `foreign_tax_credits` populated from the previous `TaxReturn`; wizard step 3 pre-fills those values without overwriting any field the user has already typed.
- [x] **P2-AC5** — Run `pytest tests/unit/engines/test_property_tax_inputs.py` and assert that CA engine accepts `property_tax_paid` (max credit: $12,000 CA), and US engine accepts `state_local_property_tax` (capped at $10,000 SALT); both inputs propagate to the corresponding `DraftReturn` line items and the deduction is reflected in `total_tax`.
- [x] **P2-AC6** — Run `pytest tests/unit/test_wizard_tooltips.py` and assert that calling `load_tooltip(jurisdiction, field_key)` for at least 10 canonical fields (e.g. `ca.rrsp_contribution`, `us.foreign_tax_credit`, `in.hra_exemption`) returns a non-empty string loaded from `src/wealthtax_agent/content/tooltips/{jurisdiction}.md`; the markdown file must exist on disk.
- [x] **P2-AC7** — Run `pytest tests/unit/test_groq_rate_limit.py` and assert that a simulated burst of 61 Groq calls within one hour for the same `user_id` raises `RateLimitExceeded` on the 61st call; confirm the counter resets after a mocked 3600-second window; no actual Groq network call is made (LLM is mocked at module level).
- [x] **P2-AC8** — Run `pytest tests/unit/test_structured_logging.py` and assert that all log records emitted by `llm.py`, `graph.py`, and `build_return.py` are valid JSON (parse with `json.loads`); assert no record contains a string matching the regex `\b\d{3}-\d{2}-\d{4}\b` (SSN-shaped), `\b\d{9}\b` (SIN-shaped), or `\b[A-Z]{5}\d{4}[A-Z]\b` (PAN-shaped).
- [ ] **P2-AC9** — Run `pytest tests/integration/test_e2e_wizard_flow.py` and assert that a pytest fixture walks steps 1-5 of the wizard via `AppTest`, submitting valid data at each step, and the final `GraphState` contains `draft_return` with `total_tax > 0` and at least one filing artifact per selected jurisdiction; the fixture uses `WEALTHTAX_MODE=self_hosted` and `GROQ_API_KEY=gsk-test-key` with the LLM mocked.
- [x] **P2-AC10** — Run `pytest tests/integration/test_streamlit_smoke.py -k cache` (new test class) and assert that calling the review-report render function twice with the same `DraftReturn` results in exactly one call to the underlying engine compute function; confirm with a `unittest.mock.patch` call count assert (`call_count == 1`).
- [x] **P2-AC11** — Run `python -m pytest tests/unit/test_wizard_tooltips.py --co -q` and confirm no test requires a `GROQ_API_KEY` or `ANTHROPIC_API_KEY` env var; `load_tooltip` must be purely file-based with no external calls.
- [x] **P2-AC12** — Run `bash scripts/check_tab_order.sh` (script reads the wizard form field definitions from `intake/wizard.py` and asserts they appear in logical DOM order: jurisdiction before year, income before deductions, deductions before review); script exits 0 when order is correct and exits 1 with a diff when a field is out of sequence.
- [x] **P2-AC13** — Run `pytest --no-cov -q` and confirm total passing count is >= 545 (Phase 1 baseline ~530 + at least 15 new Phase 2 tests); zero failures, zero errors.
- [ ] `intake/wizard.py` 5-step machine: (1) jurisdiction + year, (2) residency days, (3) income
- [ ] Auto-save to `TaxReturn(status="draft")` on each Next click; survive restart.
- [ ] Return History "Edit" button pre-populates wizard from stored (decrypted) fields.
- [ ] Sidebar step indicator (1/5 … 5/5) with back/next.
- [ ] Landing (`_render_landing()`) for unauthenticated / pre-login: product name, 3-bullet value
- [ ] Top nav: Home | New Return | My Returns | Settings.
- [ ] Dashboard (`_render_dashboard()`): return count, most recent return summary, CPA disclaimer.

## Medium Priority


## Low Priority


## Completed
- [x] Project enabled for Ralph
- [x] P2-AC6 / P2-AC11 — file-based wizard tooltip loader (CA/US/IN markdown + 25 tests, no LLM env needed)
- [x] P2-AC5 — property tax inputs: CA `property_tax_paid` ($12k cap, lowest-rate credit) + US `state_local_property_tax` (SALT $10k cap) + 10 tests
- [x] P2-AC8 — JSON structured logging (`logging_utils.py`) with SSN/SIN/PAN scrubbing; wired into `llm.py` (retry warning), `graph.py` (build_start), `build_return.py` (start + error); 10 new tests, 606→616 passing
- [x] P2-AC7 — Per-user Groq rate limiter (`services/groq_rate_limit.py`): sliding 60/3600s window, deque-backed, time-fn injectable for tests; `RateLimitExceeded` raised on 61st call, counter resets after window; 11 new tests, 616→627 passing
- [x] P2-AC13 — Total passing count target (≥545) satisfied at 627
- [x] P2-AC12 — Wizard tab-order check: `scripts/check_tab_order.sh` parses `WIZARD_STEPS` from `intake/wizard.py` and verifies DOM-natural order (jurisdiction_year → residency_days → income_sources → deductions_credits → review_submit); 8 pytest wrappers exercise happy path + 5 failure modes (swap, review-not-last, count mismatch, missing file, strict-mode stderr); 627→635 passing
- [x] P2-AC10 — Review-report rendering cache: new `render_review_report.py` module with `compute_review_totals()` (engine-side) and `render_review_report()` (memoised by sha256 fingerprint of jurisdiction + year + totals + line_items + credits + notes); 3 new tests in `TestReviewReportCache` (same-draft → 1 compute, different drafts → 2 computes, clear_cache forces recompute); 635→638 passing
- [x] P2-AC3 — `build_review_report_pdf(draft)` in `render_review_report.py` emits a one-page reportlab PDF stamped with jurisdiction-specific labels via Title/Subject/Keywords metadata + body text: CA → "T1 General"/"T1 line 15000", US → "Form 1040"/"Schedule 1", IN → "ITR"/"ITR Part B-TI"; `setPageCompression(0)` keeps text grep-able; defensive hand-rolled fallback for environments without reportlab; 9 new tests (3 magic-bytes parametrized + 3 label asserts + numeric/transmissible/missing-jurisdiction); 638→647 passing

## Notes
- Focus on MVP functionality first
- Ensure each feature is properly tested
- Update this file after each major milestone
