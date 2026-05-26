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
- [ ] `intake/wizard.py` 5-step machine: (1) jurisdiction + year, (2) residency days, (3) income
- [ ] Auto-save to `TaxReturn(status="draft")` on each Next click; survive restart.
- [ ] Return History "Edit" button pre-populates wizard from stored (decrypted) fields.
- [ ] Sidebar step indicator (1/5 … 5/5) with back/next.
- [ ] Landing (`_render_landing()`) for unauthenticated / pre-login: product name, 3-bullet value
- [ ] Top nav: Home | New Return | My Returns | Settings.
- [ ] Dashboard (`_render_dashboard()`): return count, most recent return summary, CPA disclaimer.
- [ ] All sections render without exception in `AppTest` for both modes.

## Medium Priority


## Low Priority


## Completed
- [x] Project enabled for Ralph
- [x] **S2 / AC2** — `TransmissionBlockedError` blocks `FilingArtifact(transmissible=True)` at __init__, __setattr__, and model_copy.

## Notes
- Focus on MVP functionality first
- Ensure each feature is properly tested
- Update this file after each major milestone
