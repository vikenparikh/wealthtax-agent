# WealthTax Agent — Architecture

> v0.5.0 · Python 3.10+ · LangGraph · Streamlit · Groq-hosted LLMs

## 1. What it is

WealthTax Agent is a prototype AI-assisted tax-draft assistant for individuals who file in **Canada, the United States, and/or India** — including cross-border cases. Users upload tax slips (PDF, image, Excel, CSV), type a plain-English description of their year, or enter values manually. The agent classifies and extracts every form, runs residency tests, applies real progressive tax brackets for each jurisdiction, flags cross-border edge cases (FTC, RSU sourcing, duplicate student-loan claims), emits filing-shaped artifacts (`transmissible=false`), and presents a human approval gate. It never contacts CRA, IRS, or the Indian e-filing portal.

---

## 2. Module map

| Path | Purpose |
|---|---|
| `src/wealthtax_agent/main.py` | Streamlit UI (~800 lines): auth sidebar, file upload, intake forms, results rendering, approval gate |
| `src/wealthtax_agent/graph.py` | LangGraph pipeline assembly; exposes `build_graph()` and `build_legacy_graph()` |
| `src/wealthtax_agent/state.py` | Pydantic `GraphState` and all shared types (`FormExtract`, `DraftReturn`, `FilingArtifact`, …) |
| `src/wealthtax_agent/parse_docs.py` | Bytes → text: local OCR fallback or Groq vision LLM for PDF/images; xlsx/csv ingestion |
| `src/wealthtax_agent/classify_forms.py` | Rule-based + LLM-fallback form-code classification (38 supported forms across 3 jurisdictions) |
| `src/wealthtax_agent/extract_forms.py` | Structured field extraction from classified form text |
| `src/wealthtax_agent/ingest/dedupe.py` | Content sha256 + form fingerprint deduplication across upload formats |
| `src/wealthtax_agent/corrections/` | Natural-language intake (`parse_intake_narrative`) and per-field correction with revision history |
| `src/wealthtax_agent/engines/ca_engine.py` | Canada: federal + provincial (ON/BC/AB/QC) progressive brackets, BPA, CPP/EI credits, RRSP |
| `src/wealthtax_agent/engines/us_engine.py` | US: 1040 brackets, standard deduction, CTC, FICA, preferential cap-gain rates, state tax (CA/NY/TX/FL/WA) |
| `src/wealthtax_agent/engines/in_engine.py` | India: old + new regime, 87A rebate, surcharge tiers, 4% cess, LTCG pre/post-Jul'24, 80C/80D/80E/80G/24(b), HRA, NR/RNOR/ROR |
| `src/wealthtax_agent/engines/residency.py` | US Substantial Presence Test, CA 183-day deemed residency, India §6 ROR/RNOR/NR, treaty tie-breaker notes |
| `src/wealthtax_agent/engines/cross_border.py` | Student-loan single-claim (highest-marginal), RSU sourcing (Rev. Proc. 2008-23), FTC hints |
| `src/wealthtax_agent/engines/estimated_tax.py` | IRS 1040-ES and CRA INNS3 quarterly voucher generation |
| `src/wealthtax_agent/engines/wash_sale.py` | Wash-sale detection and adjustment |
| `src/wealthtax_agent/clarify.py` | Generates targeted clarifying questions; pipeline pauses when high-priority answers are missing |
| `src/wealthtax_agent/reason_tax.py` | Engine dispatcher + cross-border guardrail node |
| `src/wealthtax_agent/optimize.py` | Legal optimization suggestions (RRSP/401k/IRA top-ups, FHSA, loss harvesting, HSA, …) |
| `src/wealthtax_agent/explain_return.py` | LLM-generated plain-language + pseudo-XML explanations |
| `src/wealthtax_agent/build_return.py` | Artifact-generation dispatcher |
| `src/wealthtax_agent/filing/ca_netfile.py` | T1 PDF summary + NETFILE-shaped XML (`transmissible=false`) |
| `src/wealthtax_agent/filing/us_mef.py` | 1040 PDF summary + IRS MeF-shaped JSON (`transmissible=false`) |
| `src/wealthtax_agent/filing/in_itr.py` | ITR JSON (PartA-GEN, ScheduleS/HP/CG/VIA, PartB-TI/TTI) (`transmissible=false`) |
| `src/wealthtax_agent/filing/quarterly.py` | Quarterly estimated-tax voucher PDFs |
| `src/wealthtax_agent/filing/pdf_fill.py` | PDF fill utility |
| `src/wealthtax_agent/llm.py` | Groq client wrapper, retry helpers, PII sanitization before LLM calls |
| `src/wealthtax_agent/auth.py` | Email/password auth, session tokens (Fernet-signed), saas vs. self_hosted mode gate |
| `src/wealthtax_agent/db/models.py` | SQLAlchemy ORM: `User`, `UserSession`, `TaxReturn`; Fernet-encrypted PII columns |
| `src/wealthtax_agent/db/crypto.py` | Fernet encrypt/decrypt helpers for PII at rest |
| `src/wealthtax_agent/db/repo.py` | Data-access layer (create/read/update for users, sessions, returns) |
| `src/wealthtax_agent/config/tax_tables/` | Versioned YAML brackets and credits per jurisdiction × year (2023/2024/2025 shipped) |
| `src/wealthtax_agent/forms/` | Per-form field schemas: `ca/`, `us/`, `in_/` |
| `src/wealthtax_agent/intake/wizard.py` | Manual-intake field specs per form |
| `src/wealthtax_agent/services/` | Business-logic services (TBD — scaffolded) |
| `src/wealthtax_agent/workers/` | Background event consumers |
| `src/wealthtax_agent/projection.py` | Year-over-year planning summary |
| `src/wealthtax_agent/persistence.py` | Revision persistence helpers |
| `tests/unit/` | Per-module unit tests (478 passing at v0.5.0) |
| `tests/integration/scenarios/` | 8 real-world cross-border golden scenarios |
| `alembic/versions/` | Database migrations |
| `docs/` | Architecture notes, deploy runbook, demo materials |
| `scripts/validate.sh` | pytest + Streamlit boot smoke; appends to `docs/run_history.md` |
| `.github/workflows/` | `tests.yml` (CI) + `deploy.yml` (GHCR → VPS via SSH) |

---

## 3. Tech stack

| Layer | Choice |
|---|---|
| Language | Python 3.10+ |
| UI | Streamlit |
| Pipeline | LangGraph (`StateGraph`) |
| State / validation | Pydantic v2 |
| ORM / migrations | SQLAlchemy + Alembic |
| Database | SQLite (dev), Postgres (prod) |
| PII encryption at rest | `cryptography.fernet.Fernet` |
| LLM provider | Groq (`llama-3.1-8b-instant` for parse/explain; `meta-llama/llama-4-scout-17b-16e-instruct` for OCR) |
| LLM client | `llm.py` (direct Groq HTTP, no Anthropic SDK) |
| OCR fallback | `LOCAL_OCR_ONLY=true` → tesseract (not present in CI) |
| Container | Docker (Python 3.11-slim, ~250 MB) |
| Ingress | Cloudflare Tunnel (no inbound ports) |
| CI/CD | GitHub Actions → GHCR → SSH pull-deploy |
| Test framework | pytest + pytest-xdist |
| Tax-table config | Versioned YAML per jurisdiction × year |

---

## 4. Data flow

```
User uploads files / types NL description / enters values manually
        │
        ▼
parse_docs_node         bytes → text (Groq vision LLM or local OCR; xlsx/csv direct)
        │
        ▼
dedupe_extracts_node    sha256 + form fingerprint; drops duplicate slips across formats
        │
        ▼
classify_forms_node     rule-based → form_code + jurisdiction; LLM fallback on miss
        │
        ▼
extract_forms_node      structured FormExtract{fields, text_fields} per form
        │
        ▼
residency_test_node     days-per-country → resident status + treaty tie-breaker notes
        │
        ▼
apply_corrections_node  NL intake narrative → patches extracts; staged field edits applied
        │
        ▼
ask_clarifications_node emits ClarifyingQuestion list; pipeline pauses if high-priority
        │           (UI re-renders questions; user answers; graph re-invoked)
        ▼
reason_tax_node         dispatches into ca_engine / us_engine / in_engine;
                        cross_border guardrails applied (FTC, student-loan, RSU)
        │
        ▼
optimize_node           OptimizationSuggestion list per jurisdiction
        │
        ▼
explain_return_node     LLM generates plain-language + pseudo-XML explanation
        │
        ▼
build_return_node       FilingArtifact list: T1+XML (CA), 1040+JSON (US), ITR JSON (IN),
                        quarterly vouchers (CA+US when self-employment threshold crossed)
        │
        ▼
format_outputs_node     final GraphState → Streamlit renders draft totals, artifacts,
                        optimizations, and human approval gate
        │
        ▼
[Human approves]        User clicks "Approve this draft (I take responsibility)"
                        → persist_revision saves to DB; artifacts available for download
                        → agent DOES NOT transmit to CRA / IRS / India e-filing portal
```

---

## 5. Storage

| What | Where | Encryption |
|---|---|---|
| User accounts | `users` table (SQLite dev / Postgres prod) | `full_name_enc`, `sin_or_ssn_enc`, `dob_enc`, `address_enc` → Fernet ciphertext |
| Session tokens | `user_sessions` table | Fernet-signed |
| Tax returns / extracts | `TaxReturn` table; `fields` column as JSON | Application-layer: structured fields stored as JSON, not individually encrypted |
| Filing artifacts | In-memory during session; base64 in `FilingArtifact.content_b64` | Not persisted to disk independently |
| Tax-table brackets | `config/tax_tables/*.yaml` | Plaintext config; no user data |
| LLM inputs | Sanitized via `llm.py` before transmission to Groq | PII-stripping applied; no local audit log of LLM payloads |

**Gaps:** LLM call payloads are sent to Groq (third party). If a user uploads a slip containing raw PII (name, SIN, SSN), that data traverses the Groq API. There is sanitization in `llm.py` but no formal data-processing agreement or audit log documented.

---

## 6. Safety / compliance

| Control | Status |
|---|---|
| Human approval gate (explicit "I take responsibility" click) | Implemented |
| All artifacts stamped `transmissible=false` | Implemented |
| No direct CRA / IRS / India e-filing transmission | Implemented (by omission) |
| Fernet encryption on PII columns at rest | Implemented |
| CPA / legal disclaimer on AI outputs | Implemented (`test_cpa_chat.py` asserts it is always present) |
| Auth in saas mode (email + password) | Implemented |

**Honest gaps (prototype, not production):**

- No SOC 2, PCI, or PIPEDA audit. This is a Wealthsimple hackathon prototype.
- No formal DPA with Groq — raw slip text (potentially containing SIN/SSN/PAN) is sent to their API.
- Password storage uses hashed passwords (field present) but the hashing scheme is not verified here — verify `auth.py` before production use.
- No rate limiting, brute-force protection, or MFA.
- No data-deletion (right to erasure) workflow.
- Tax calculations use real bracket tables but have not been independently audited by a CPA or tax attorney. Output is explicitly advisory.
- `transmissible=false` is a flag in the output JSON/XML, not a technical enforcement mechanism.

---

## 7. Agent architecture

Single LangGraph pipeline — not a multi-agent system. One `StateGraph` with 10 sequential nodes; the only branching is the clarification pause (conditional edge: `has_outstanding_clarifications → pause | continue`).

**LLM usage:**

| Role | Model | When |
|---|---|---|
| OCR / form parsing | `meta-llama/llama-4-scout-17b-16e-instruct` (Groq vision) | PDF/image uploads when `LOCAL_OCR_ONLY=false` |
| Form classification fallback | `llama-3.1-8b-instant` | When rule-based classifier misses |
| Field extraction | `llama-3.1-8b-instant` | LLM path in `extract_forms.py` |
| Plain-language explanation | `llama-3.1-8b-instant` | Always in `explain_return_node` |
| NL intake parsing | `llama-3.1-8b-instant` | When user types a narrative description |

Rule-based logic handles all tax arithmetic — LLMs are used only for document understanding and explanation, never for bracket calculations.

**No tools / function-calling in use.** The pipeline is a deterministic graph; LLM outputs are parsed and validated into Pydantic models before any downstream use.

---

## 8. Key entry points

| Entry point | Purpose |
|---|---|
| `src/wealthtax_agent/main.py:run_app()` | Streamlit app entrypoint — renders all UI sections |
| `src/wealthtax_agent/graph.py:build_graph()` | Returns compiled LangGraph `CompiledStateGraph` |
| `src/wealthtax_agent/db/__init__.py:create_all_for_tests()` | In-memory SQLite DB init for tests |
| `alembic upgrade head` | Apply all DB migrations (required before first prod run) |
| `scripts/validate.sh` | Canonical local validation: pytest + Streamlit boot |

**UI sections (rendered by `run_app()`):**

| Section | Function |
|---|---|
| Auth sidebar (saas mode) | `_render_auth_sidebar()` |
| Return history | `_render_return_history()` |
| File upload + NL intake | inline in `run_app()` |
| Manual intake expander | `_render_manual_intake()` |
| Unsupported form notice | `_render_unsupported_section()` |
| Clarifying questions | `_render_clarifying_questions()` |
| Draft return totals | `_render_draft_returns()` |
| Optimization suggestions | `_render_optimizations()` |
| Filing artifact downloads | `_render_artifacts()` |
| Correction chat | `_render_correction_chat()` |
| Inline field edit | `_render_inline_edit()` |
| Revision diff | `_render_diff()` |

---

## 9. Adding a new tax jurisdiction or calculation

**New jurisdiction (e.g., UK):**

1. Add form schemas under `src/wealthtax_agent/forms/<jk>/`.
2. Register form codes in `classify_forms.py` rule table; add LLM fallback examples.
3. Add field extraction rules in `extract_forms.py` or a new extractor.
4. Create `src/wealthtax_agent/engines/<jk>_engine.py` implementing the same interface as `ca_engine.py` (`compute_tax(extracts, answers, config) → DraftReturn`).
5. Add tax-table YAMLs under `src/wealthtax_agent/config/tax_tables/<jk>/YYYY.yaml`.
6. Wire the engine into `reason_tax.py` dispatcher.
7. Add filing artifact builders under `src/wealthtax_agent/filing/<jk>_*.py`.
8. Wire artifacts into `build_return.py`.
9. Add clarifying questions to `src/wealthtax_agent/config/clarifying_questions/`.
10. Add golden scenarios to `tests/integration/scenarios/test_scenarios_all.py`.

**New bracket year (e.g., 2026):**

1. Copy the previous year's YAML from `config/tax_tables/<jk>/2025.yaml` → `2026.yaml`.
2. Update brackets, rates, and credit amounts per official government publications.
3. Add the year to the multi-year selector in `_available_years_combined()` in `main.py`.
4. Run existing tests — scenario fixtures are year-parameterized so you will see failures for any changed bracket logic.

**New form (within an existing jurisdiction):**

1. Add field schema to `src/wealthtax_agent/forms/<jk>/<FORM_CODE>.py`.
2. Add classification rule in `classify_forms.py`.
3. Add extraction rule in `extract_forms.py` (rule path first; LLM fallback optional).
4. Wire extracted fields into the relevant engine's computation logic.
5. Add a unit test in `tests/unit/forms/`.

---

## 10. Run commands

```bash
# Install
pip install -r requirements.txt

# Run UI (self-hosted, single-user, no auth)
WEALTHTAX_MODE=self_hosted \
GROQ_API_KEY=gsk-... \
WEALTHTAX_FERNET_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())") \
PYTHONPATH=src python -m streamlit run src/wealthtax_agent/main.py

# Run UI (saas mode, with auth sidebar)
WEALTHTAX_MODE=saas GROQ_API_KEY=gsk-... WEALTHTAX_FERNET_KEY=... \
PYTHONPATH=src python -m streamlit run src/wealthtax_agent/main.py

# Tests
PYTHONPATH=src python -m pytest --no-cov -q                          # all (478 at v0.5.0)
PYTHONPATH=src python -m pytest tests/integration/scenarios/ -v      # cross-border golden scenarios
PYTHONPATH=src python -m pytest tests/integration/test_streamlit_smoke.py -v  # UI smoke

# Validate (tests + Streamlit boot + run_history.md append)
./scripts/validate.sh

# DB migrations (Postgres prod)
PYTHONPATH=src alembic upgrade head

# Docker (dev — builds locally)
docker compose up -d

# Docker (prod — pulls from GHCR, includes cloudflared sidecar)
docker compose -f docker-compose.prod.yml up -d

# Environment variables (required)
# GROQ_API_KEY          Groq API key
# WEALTHTAX_FERNET_KEY  Fernet key for PII encryption (generate once, store safely)
# WEALTHTAX_MODE        saas | self_hosted (default: self_hosted)

# Environment variables (optional overrides)
# LLM_PROVIDER          groq (default)
# OCR_MODEL             meta-llama/llama-4-scout-17b-16e-instruct
# PARSE_MODEL / EXPLAIN_MODEL  llama-3.1-8b-instant
# LOCAL_OCR_ONLY        true → skip Groq vision, use tesseract
# MAX_UPLOAD_FILES      default 20
# POSTGRES_DSN          for Postgres in prod (else SQLite)
```

---

*See also: [docs/architecture.md](docs/architecture.md) (deeper notes), [docs/DEPLOY.md](docs/DEPLOY.md) (VPS + Cloudflare runbook), [CLAUDE.md](CLAUDE.md) (session handoff state).*
